---
titulo: Etapa 12 — Few-shot + RAG com base de conhecimento local
data: 2026-05-25
status: concluída
depende-de: etapa-11-runbook-generation.md
---

# Etapa 12 — Few-shot + RAG com base de conhecimento local

## Objetivo

Transformar o agente de genérico para contextualizado: em vez de raciocinar do zero a cada
alerta, ele consulta uma base de conhecimento local com histórico de incidentes e exemplos
curados antes de gerar a análise.

**Problema que esta etapa resolve:**

O agente da Etapa 11 gera boas análises, mas trata cada alerta como se fosse o primeiro.
Não aproveita runbooks de incidentes anteriores do mesmo tipo, nem exemplos de análises ideais
do formato esperado pelo time. O resultado é análises mais genéricas e inconsistentes.

---

## O que foi implementado

### `agent/knowledge_base.py` — `KnowledgeBase`

Base de conhecimento local sem dependências externas (sem embeddings, sem vetordb):

```
data/knowledge/
├── examples/        # exemplos curados (few-shot) — versionados no git
│   ├── zeebe-backpressure-growing.md
│   └── zeebe-memory-predicted-high.md
└── runbooks/        # runbooks gerados pelo agente em runtime — gitignored
    └── <alert-slug>-<md5[:8]>.md
```

**Ciclo de vida:**
1. Na inicialização do processo: carrega todos os exemplos curados + runbooks persistidos do disco
2. A cada alerta recebido: `_kb.search(alert_name, k=2)` retorna os documentos mais relevantes
3. Após geração do runbook: `_kb.add_document(...)` persiste no disco e indexa em memória

### Scoring (sem embeddings)

```
score(doc, query):
  +10.0  se doc.alert_name == query (case-insensitive)  ← match exato
  +overlap(alert_name_tokens) / len(query_tokens)       ← overlap de tokens
  +0.1 * overlap(content_tokens) / len(query_tokens)    ← overlap no conteúdo
```

Documentos com `score == 0` são excluídos. Retorna top-k por score decrescente.

> **Por que não usar embeddings?** Os nomes de alertas (`ZeebeBackpressureGrowing`) são
> identificadores únicos e altamente específicos. Match exato + overlap de tokens é suficiente
> e elimina qualquer dependência externa — mantendo o projeto 100% air-gapped.

### Few-shot via exemplos curados

Cada arquivo em `data/knowledge/examples/` tem frontmatter YAML com `alert_name:`:

```markdown
---
alert_name: ZeebeBackpressureGrowing
type: example
severity: critical
---
# Exemplo de análise — ZeebeBackpressureGrowing
...análise no formato exato esperado pelo time...
```

O agente usa esses exemplos como referência de formato e nível de detalhe — sem treinar o modelo.

### Injeção no contexto (`agent/prompts.py`)

Quando a KB encontra documentos relevantes, `build_user_message` injeta uma seção antes do alerta:

```
## Contexto relevante — histórico do time

### Exemplo de análise — ZeebeBackpressureGrowing
<conteúdo do exemplo curado>

---
[alerta atual segue abaixo]
```

Labels visuais distinguem a origem:
- `"Exemplo de análise"` → documento curado (few-shot)
- `"Runbook anterior"` → runbook gerado pelo agente em incidente anterior

---

## Decisões técnicas

### Sem embeddings, sem vetordb

**Decisão:** scoring por match exato de alertname + overlap de tokens.

**Por quê:** alertnames são identificadores únicos e determinísticos.
`ZeebeBackpressureGrowing` é 100% específico — não há ambiguidade semântica que embeddings
resolveriam. A abordagem mantém o projeto air-gapped, sem `sentence-transformers`, `faiss`,
`chromadb` ou qualquer outra dependência de ML.

**Limitação aceita:** documentos com conteúdo relevante mas alertname diferente têm score baixo.
Aceitável no estágio atual — o caso de uso principal é "já vi esse alerta antes?"

### `_tokenize` não divide CamelCase

`_tokenize("ZeebeMemoryPredictedHigh")` → `{"zeebememorypredicted"}` (um token).

**Por quê:** simplicidade. `re.findall(r"[a-zA-Z0-9]+", text.lower())` é suficiente para
o caso de uso. Dividir CamelCase adicionaria complexidade sem benefício mensurável dado que
o match exato de alertname já captura os casos mais importantes.

**Implicação no content overlap:** para aproveitar o scoring de conteúdo, exemplos curados
devem conter o alertname em lowercase (`zeebememorypredicted`) ou variações tokenizáveis.

### Persistência em disco (runbooks apenas)

Apenas documentos `source="generated"` são persistidos em disco (`data/knowledge/runbooks/`).
Exemplos curados (`source="curated"`) são versionados no git e carregados somente da memória.

**Por quê:** runbooks gerados são artefatos de runtime — mudam a cada ciclo de incidente.
Versioná-los no git criaria ruído e conflitos. A pasta está no `.gitignore`.

### Excerpts limitados a 500 chars na injeção

`Document.excerpt(max_chars=500)` trunca o conteúdo injetado no contexto.

**Por quê:** o modelo `qwen2.5:7b` tem context window limitado. Injetar documentos completos
(que podem ter 2KB+) comprime o espaço disponível para a análise. 500 chars capturam
o diagnóstico principal sem ocupar o contexto inteiro.

---

## Estrutura de arquivos

```
agent/
└── knowledge_base.py       # KnowledgeBase, Document, _tokenize

data/knowledge/
├── examples/
│   ├── zeebe-backpressure-growing.md    # few-shot: alerta critical
│   └── zeebe-memory-predicted-high.md  # few-shot: alerta warning
└── runbooks/                            # gitignored — populado em runtime
```

---

## Como adicionar novos exemplos curados

1. Criar arquivo em `data/knowledge/examples/<alertname-kebab>.md`
2. Adicionar frontmatter com `alert_name: NomeCamelCase`
3. Escrever a análise no formato exato esperado pelo time (veja os exemplos existentes)
4. Commitar — o exemplo é carregado automaticamente na próxima inicialização do agente

Não é necessário reiniciar o agente em produção para novos runbooks (gerados em runtime),
mas **é necessário** para novos exemplos curados (carregados apenas na inicialização).
