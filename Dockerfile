FROM python:3.11-slim

# Usuário não-root — boa prática de segurança em containers
RUN groupadd --gid 1000 aiops && \
    useradd --uid 1000 --gid aiops --shell /bin/bash --create-home aiops

WORKDIR /app

# Camada de dependências separada do código para melhor cache de build.
# Versões espelham exatamente o pyproject.toml — atualize os dois juntos.
RUN pip install --no-cache-dir \
    "openai>=1.30.0,<2.0.0" \
    "fastapi>=0.115.0,<1.0.0" \
    "uvicorn>=0.32.0,<1.0.0" \
    "httpx>=0.27.0,<1.0.0" \
    "prometheus-client>=0.20.0,<1.0.0"

# Código do agente e artefatos necessários em runtime
COPY agent/    ./agent/
COPY prompts/  ./prompts/

# Exemplos curados de RAG ficam na imagem — runbooks gerados vêm do PVC
COPY data/knowledge/examples/ ./data/knowledge/examples/

# Cria o diretório de runbooks (substituído pelo PVC em produção)
RUN mkdir -p data/knowledge/runbooks && \
    chown -R aiops:aiops /app

USER aiops

# uvicorn é iniciado a partir de agent/ para que os imports internos funcionem
WORKDIR /app/agent

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:5001/health', timeout=3).raise_for_status()"

CMD ["uvicorn", "webhook_receiver:app", "--host", "0.0.0.0", "--port", "5001"]
