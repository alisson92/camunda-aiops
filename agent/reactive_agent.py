"""
Agente reativo: recebe contexto de um alerta, chama ferramentas Prometheus
via tool use (OpenAI-compatible API → Ollama local) e retorna análise estruturada.

Nenhum dado sai da máquina: Ollama roda localmente, Prometheus é acessado via
port-forward local. Zero dependência de APIs externas.
"""

import json
import logging

from openai import OpenAI

from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from metrics import LLM_TOOL_CALLS
from prompts import SYSTEM_PROMPT, build_user_message
from tools import TOOL_DISPATCH, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6  # limite de segurança para o agentic loop


def run_agent(
    alert_name: str,
    alert_labels: dict,
    alert_annotations: dict,
    status: str = "firing",
    context_docs: list | None = None,
) -> str:
    """
    Executa o loop do agente para um alerta recebido.
    context_docs: documentos relevantes da KnowledgeBase injetados no contexto do LLM.
    Retorna a análise final como string.
    """
    # api_key="ollama" é um placeholder obrigatório pelo SDK — Ollama não valida o valor
    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(alert_name, alert_labels, alert_annotations, status, context_docs)},
    ]

    logger.info("Iniciando análise: alerta=%s status=%s modelo=%s", alert_name, status, OLLAMA_MODEL)

    for round_n in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            # tool_choice="auto" é o padrão — o modelo decide quando usar ferramentas
        )

        choice = response.choices[0]
        messages.append(choice.message)

        if choice.finish_reason == "stop":
            final_text = choice.message.content or "[sem resposta textual]"
            logger.info("Análise concluída em %d rodada(s).", round_n + 1)
            return final_text

        if choice.finish_reason != "tool_calls":
            logger.warning("finish_reason inesperado: %s", choice.finish_reason)
            return f"[agent] finish_reason inesperado: {choice.finish_reason}"

        # Processa todas as chamadas de ferramentas desta rodada
        for tool_call in (choice.message.tool_calls or []):
            tool_name = tool_call.function.name
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                tool_input = {}
                logger.warning("Erro ao parsear argumentos de %s: %s", tool_name, e)

            logger.info("Ferramenta: %s(%s)", tool_name, json.dumps(tool_input, ensure_ascii=False))
            LLM_TOOL_CALLS.labels(tool_name=tool_name).inc()

            fn = TOOL_DISPATCH.get(tool_name)
            if fn is None:
                result = {"error": f"Ferramenta desconhecida: {tool_name}"}
            else:
                try:
                    result = fn(**tool_input)
                except Exception as e:
                    result = {"error": str(e)}

            logger.debug("Resultado de %s: %s", tool_name, json.dumps(result, ensure_ascii=False)[:300])

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    logger.warning("Limite de %d rodadas atingido sem conclusão.", MAX_TOOL_ROUNDS)
    return "[agent] Limite de rodadas de ferramentas atingido sem conclusão."
