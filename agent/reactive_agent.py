"""
Agente reativo: recebe contexto de um alerta, chama ferramentas Prometheus
via tool use (OpenAI-compatible API → Ollama local) e retorna análise estruturada.

Nenhum dado sai da máquina: Ollama roda localmente, Prometheus é acessado via
port-forward local. Zero dependência de APIs externas.
"""

import json
import os
from pathlib import Path

from openai import OpenAI
from tools import TOOL_SCHEMAS, TOOL_DISPATCH
from prompts import SYSTEM_PROMPT, build_user_message

# Carrega .env do diretório do agente, se existir — sem dependência de python-dotenv
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
MAX_TOOL_ROUNDS = 6  # limite de segurança para o agentic loop


def run_agent(alert_name: str, alert_labels: dict, alert_annotations: dict, status: str = "firing") -> str:
    """
    Executa o loop do agente para um alerta recebido.
    Retorna a análise final como string.
    """
    # api_key="ollama" é um placeholder obrigatório pelo SDK — Ollama não valida o valor
    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(alert_name, alert_labels, alert_annotations, status)},
    ]

    print(f"\n[agent] Iniciando análise para alerta: {alert_name} ({status})")
    print(f"[agent] Modelo: {OLLAMA_MODEL} | Endpoint: {OLLAMA_BASE_URL}")

    for round_n in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            # tool_choice="auto" é o padrão — o modelo decide quando usar ferramentas
        )

        choice = response.choices[0]

        # Adiciona a resposta do modelo ao histórico (objeto message do OpenAI SDK)
        messages.append(choice.message)

        if choice.finish_reason == "stop":
            # Agente concluiu sem mais chamadas de ferramenta
            final_text = choice.message.content or "[sem resposta textual]"
            print(f"[agent] Análise concluída após {round_n + 1} rodada(s).")
            return final_text

        if choice.finish_reason != "tool_calls":
            return f"[agent] finish_reason inesperado: {choice.finish_reason}"

        # Processa todas as chamadas de ferramentas desta rodada
        tool_calls = choice.message.tool_calls or []
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                tool_input = {}
                print(f"[agent] Erro ao parsear argumentos de {tool_name}: {e}")

            print(f"[agent] Chamando ferramenta: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

            fn = TOOL_DISPATCH.get(tool_name)
            if fn is None:
                result = {"error": f"Ferramenta desconhecida: {tool_name}"}
            else:
                try:
                    result = fn(**tool_input)
                except Exception as e:
                    result = {"error": str(e)}

            print(f"[agent] Resultado de {tool_name}: {json.dumps(result, ensure_ascii=False)[:300]}...")

            # Resultado de ferramenta no formato OpenAI
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "[agent] Limite de rodadas de ferramentas atingido sem conclusão."
