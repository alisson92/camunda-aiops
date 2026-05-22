"""
Agente reativo: recebe contexto de um alerta, chama ferramentas Prometheus
via tool use da Claude API e retorna análise estruturada.
"""

import json
import os
from pathlib import Path
import anthropic
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

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ROUNDS = 6  # limite de segurança para o agentic loop


def run_agent(alert_name: str, alert_labels: dict, alert_annotations: dict, status: str = "firing") -> str:
    """
    Executa o loop do agente para um alerta recebido.
    Retorna a análise final como string.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages = [
        {
            "role": "user",
            "content": build_user_message(alert_name, alert_labels, alert_annotations, status),
        }
    ]

    print(f"\n[agent] Iniciando análise para alerta: {alert_name} ({status})")

    for round_n in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Adiciona a resposta do modelo ao histórico
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Agente concluiu — extrai texto final
            final_text = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "[sem resposta textual]",
            )
            print(f"[agent] Análise concluída após {round_n + 1} rodada(s).")
            return final_text

        if response.stop_reason != "tool_use":
            return f"[agent] Stop reason inesperado: {response.stop_reason}"

        # Processa todas as chamadas de ferramentas desta rodada
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
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
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        messages.append({"role": "user", "content": tool_results})

    return "[agent] Limite de rodadas de ferramentas atingido sem conclusão."
