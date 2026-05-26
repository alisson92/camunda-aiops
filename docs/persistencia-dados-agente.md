# Persistência de Dados do Agente — Análise e Trade-offs

**Contexto:** Discussão levantada pelo time após a demo. Hoje o agente reinicia "zerado" — todo o conhecimento acumulado (runbooks gerados, histórico de incidentes, cache de deduplicação) é perdido quando o processo é reiniciado. Este documento mapeia o que precisa ser persistido, as opções disponíveis e os trade-offs de cada uma.

---

## O problema atual

O agente possui três categorias de estado em memória:

| Dado | Localização atual | Perdido no restart? | Impacto |
|---|---|---|---|
| Runbooks gerados (`_runbooks` dict) | Memória Python | Sim | Links "📖 Runbook" nos cards Teams quebram |
| Base de conhecimento RAG (`KnowledgeBase`) | `data/knowledge/runbooks/` no filesystem do container | Sim (container efêmero) | Agente recomeça sem histórico de incidentes anteriores — RAG degradado |
| Cache de deduplicação (`_dedup_cache`) | Memória Python | Sim | No pior caso: reprocessa um alerta duplicado após restart |

O `_dedup_cache` é o menos crítico — seu TTL já é 300s e alertas `resolved` nunca são deduplicados. Os dois primeiros têm impacto direto na qualidade das análises e na experiência do time ao receber notificações.

---

## O que precisaria ser persistido

### 1. Base de conhecimento RAG (`data/knowledge/`)

É o dado mais valioso. Contém:
- **Exemplos curados pelo time** (`data/knowledge/examples/`) — runbooks escritos manualmente para `ZeebeBackpressureGrowing`, `ZeebeMemoryPredictedHigh`, etc.
- **Runbooks gerados automaticamente** (`data/knowledge/runbooks/`) — acumulados a cada alerta processado; formam o histórico de incidentes do time

Quanto mais tempo esse histórico existe, melhor o RAG — o agente começa a reconhecer padrões recorrentes e injeta contexto relevante nas análises.

### 2. Store de runbooks (`_runbooks` dict)

Mapeamento `alert_id → (markdown, html)` usado pelo endpoint `GET /runbook/{alert_id}`. Hoje é perdido no restart. Persistir como arquivo JSON em disco resolve com zero dependência externa.

---

## Opções de persistência

### Opção A — PVC (PersistentVolumeClaim) no Kubernetes

Montar um PVC no path `data/` do container. A `KnowledgeBase` já escreve arquivos lá — persistiria automaticamente sem mudar uma linha de código do agente.

```yaml
# Trecho do manifesto/Helm values
volumeMounts:
  - name: agent-data
    mountPath: /app/data

volumes:
  - name: agent-data
    persistentVolumeClaim:
      claimName: camunda-aiops-data
```

**Trade-offs:**

| Prós | Contras |
|---|---|
| Zero mudança no código do agente | Requer Kubernetes (não funciona no `make run` local) |
| A `KnowledgeBase` persiste automaticamente | PVC tem custo (storage class, disco provisionado) |
| Rollback simples: basta desmontar o PVC | Backup do PVC precisa de estratégia separada (Velero, snapshots) |
| Compatível com `StatefulSet` ou `Deployment` com `ReadWriteOnce` | `ReadWriteOnce` impede múltiplas réplicas simultâneas no mesmo PVC |

### Opção B — Banco de dados leve (SQLite)

Trocar o store em memória e os arquivos markdown por SQLite em `data/agent.db`. Permite queries, índices, e controle de TTL via `DELETE WHERE created_at < now() - interval`.

**Trade-offs:**

| Prós | Contras |
|---|---|
| TTL implementável por query SQL | Requer refactor do `KnowledgeBase` e do `_runbooks` store |
| Queries de busca mais eficientes que glob de arquivos | Adiciona dependência (mesmo que SQLite seja embutido) |
| Arquivo único — backup trivial (`cp agent.db`) | Não escala para múltiplas réplicas sem migrar para PostgreSQL |
| Funciona local e no cluster | Overhead de desenvolvimento maior |

### Opção C — Object storage (S3 / MinIO)

Escrever runbooks e base de conhecimento em bucket S3 ou MinIO local. Adequado se o time já usa AWS ou quer separar o dado do ciclo de vida do pod.

**Trade-offs:**

| Prós | Contras |
|---|---|
| Escala horizontalmente (múltiplas réplicas sem conflito) | Latência de I/O maior (rede vs. disco local) |
| Políticas de ciclo de vida nativas (S3 Lifecycle, TTL por prefixo) | Dependência externa (fora do cluster) para ambiente air-gapped |
| Backup e versionamento nativos | Requer refactor do `KnowledgeBase` para client S3 |
| Custo por GB é baixo em AWS | MinIO como alternativa local adiciona outro componente ao cluster |

---

## Política de retenção (rotação de dados)

Independente da opção de storage escolhida, acumular dados indefinidamente gera custo e ruído. Runbooks de incidentes de 2 anos atrás provavelmente têm pouca relevância para alertas de hoje.

### Estratégia 1 — CronJob Kubernetes

Um CronJob que roda periodicamente e deleta arquivos/registros mais antigos que `KNOWLEDGE_TTL_DAYS`.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: aiops-data-cleanup
spec:
  schedule: "0 2 * * 0"  # domingo às 02h
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: cleanup
              image: busybox
              command:
                - sh
                - -c
                - find /data/knowledge/runbooks -mtime +30 -name "*.md" -delete
          restartPolicy: OnFailure
          volumeMounts:
            - name: agent-data
              mountPath: /data
```

**Trade-offs:** zero mudança no agente, operação completamente externa e auditável. Contra: não distingue entre runbooks de alertas críticos (que talvez valha manter mais) e alertas informativos.

### Estratégia 2 — TTL no código do agente

A `KnowledgeBase` verifica a data de criação ao carregar documentos e descarta os mais antigos que `KNOWLEDGE_TTL_DAYS` (variável de ambiente).

**Trade-offs:** permite lógica mais fina — por exemplo, manter runbooks de alertas `critical` por 90 dias e `warning` por 30 dias. Contra: acoplado ao código Python, requer testes adicionais, e o TTL fica "invisível" para quem opera o cluster.

### Estratégia 3 — S3 Lifecycle Policy (se Opção C)

Bucket com regra de expiração automática por prefixo:
- `runbooks/critical/` — expirar após 90 dias
- `runbooks/warning/` — expirar após 30 dias
- `runbooks/info/` — expirar após 15 dias

**Trade-offs:** a política de retenção fica declarativa no próprio storage, sem código. Requer que os runbooks sejam escritos em subpastas por severidade (pequena mudança no `KnowledgeBase`).

---

## Recomendação para o ambiente atual

Considerando que o projeto ainda roda em Kind local e o foco é a demo + evolução gradual:

**Curto prazo (sem mudança de código):**
- Montar volume local no `docker run` ou `docker-compose` apontando para `./data` — persiste entre restarts do container sem precisar de Kubernetes
- Ou: `make run` com `DATA_DIR` apontando para um diretório fora do projeto

**Médio prazo (deploy em Kubernetes):**
- **PVC + CronJob** é o caminho de menor fricção: não muda o código, operação é declarativa em YAML, TTL ajustável via variável de ambiente no CronJob
- StorageClass `standard` (Kind) ou `gp3` (EKS) com 1–5 Gi é mais que suficiente para anos de runbooks em markdown

**Longo prazo (múltiplas réplicas / escalabilidade):**
- Migrar para SQLite (se single-node) ou PostgreSQL/MinIO (se multi-replica)
- Nesse ponto, vale avaliar se o `KnowledgeBase` customizado ainda faz sentido ou se uma solução com embeddings reais (pgvector, ChromaDB) entrega qualidade superior

---

## Estimativa de volume de dados

Para calibrar o tamanho do PVC:

- Runbook médio gerado pelo agente: ~2–5 KB (markdown)
- 10 alertas/dia × 30 dias = 300 runbooks × 5 KB = **~1,5 MB/mês**
- Com TTL de 90 dias: teto de ~4,5 MB para runbooks gerados
- Exemplos curados pelo time: dezenas de arquivos, < 1 MB total

**Conclusão:** o volume de dados é pequeno. Um PVC de 1 Gi cobre anos de operação. O custo de storage não é o driver — a discussão sobre retenção é mais sobre higiene operacional e relevância do RAG do que sobre custo real.
