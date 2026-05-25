"""
Base de conhecimento do agente — RAG simples sem dependência externa.

Dois tipos de documentos:
- curated:   exemplos ideais de análise em data/knowledge/examples/ (checados no git)
- generated: runbooks gerados pelo agente em data/knowledge/runbooks/ (gitignored)

Scoring de relevância:
- Match exato de alertname → prioridade máxima (+10.0)
- Sobreposição de tokens no alertname → score parcial
- Sobreposição de tokens no conteúdo → peso baixo (0.1×)

Sem embedding, sem dependência externa — adequado para ambiente air-gapped.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data" / "knowledge"

_FRONTMATTER_ALERT = re.compile(r"^alert_name:\s*(.+)$", re.MULTILINE)
_RUNBOOK_TITLE = re.compile(r"^#\s+Runbook:\s+(.+)$", re.MULTILINE)


@dataclass
class Document:
    doc_id: str
    title: str
    content: str
    alert_name: str = ""
    source: str = "generated"  # "generated" | "curated"

    def excerpt(self, max_chars: int = 500) -> str:
        """Trecho do documento para injeção no contexto do LLM."""
        if len(self.content) <= max_chars:
            return self.content
        return self.content[:max_chars] + "\n\n*(truncado)*"


class KnowledgeBase:
    """
    Base de conhecimento local com persistência em disco e busca por relevância.

    Uso típico:
        kb = KnowledgeBase()
        docs = kb.search("ZeebeBackpressureGrowing", k=2)
        kb.add_document("my-id", "Runbook: Alert", content, alert_name="ZeebeAlert")
    """

    def __init__(self, data_dir: Path = _DATA_DIR):
        self._data_dir = data_dir
        self._runbooks_dir = data_dir / "runbooks"
        self._examples_dir = data_dir / "examples"
        self._documents: dict[str, Document] = {}
        self._ensure_dirs()
        self._load_examples()
        self._load_runbooks()

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        self._runbooks_dir.mkdir(parents=True, exist_ok=True)
        self._examples_dir.mkdir(parents=True, exist_ok=True)

    def _load_examples(self) -> None:
        count = 0
        for path in sorted(self._examples_dir.glob("*.md")):
            doc_id = f"example-{path.stem}"
            content = path.read_text(encoding="utf-8")
            alert_name = self._extract_alert_name(content, path.stem)
            title = self._extract_title(content) or path.stem
            self._documents[doc_id] = Document(
                doc_id=doc_id,
                title=title,
                content=content,
                alert_name=alert_name,
                source="curated",
            )
            count += 1
        if count:
            logger.info("KB: %d exemplos curados carregados.", count)

    def _load_runbooks(self) -> None:
        count = 0
        for path in sorted(self._runbooks_dir.glob("*.md")):
            doc_id = path.stem
            content = path.read_text(encoding="utf-8")
            alert_name = self._extract_alert_name_from_runbook(content)
            title = self._extract_title(content) or path.stem
            self._documents[doc_id] = Document(
                doc_id=doc_id,
                title=title,
                content=content,
                alert_name=alert_name,
                source="generated",
            )
            count += 1
        if count:
            logger.info("KB: %d runbooks carregados do disco.", count)

    # ------------------------------------------------------------------
    # Helpers de parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_alert_name(content: str, stem: str) -> str:
        """Extrai alertname do frontmatter YAML ou infere pelo nome do arquivo."""
        if m := _FRONTMATTER_ALERT.search(content):
            return m.group(1).strip()
        # Heurística: converte kebab-case para CamelCase
        return "".join(word.capitalize() for word in stem.replace("-", " ").split())

    @staticmethod
    def _extract_alert_name_from_runbook(content: str) -> str:
        """Extrai alertname do cabeçalho '# Runbook: AlertName'."""
        if m := _RUNBOOK_TITLE.search(content):
            return m.group(1).strip()
        return ""

    @staticmethod
    def _extract_title(content: str) -> str:
        """Extrai o primeiro heading # do documento."""
        for line in content.splitlines():
            stripped = line.lstrip("# ").strip()
            if stripped and line.startswith("#"):
                return stripped
        return ""

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def add_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        alert_name: str = "",
        source: str = "generated",
    ) -> None:
        """Adiciona ou atualiza um documento na base. Runbooks gerados são persistidos em disco."""
        doc = Document(
            doc_id=doc_id,
            title=title,
            content=content,
            alert_name=alert_name,
            source=source,
        )
        self._documents[doc_id] = doc
        if source == "generated":
            self._persist(doc)

    def _persist(self, doc: Document) -> None:
        path = self._runbooks_dir / f"{doc.doc_id}.md"
        path.write_text(doc.content, encoding="utf-8")
        logger.debug("KB: runbook persistido em %s", path)

    def search(self, alert_name: str, k: int = 2) -> list[Document]:
        """Retorna até k documentos mais relevantes para o alertname dado."""
        if not self._documents:
            return []
        query_tokens = _tokenize(alert_name)
        scored = [
            (self._score(doc, alert_name, query_tokens), doc)
            for doc in self._documents.values()
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored[:k] if score > 0]

    def _score(self, doc: Document, alert_name: str, query_tokens: set[str]) -> float:
        score = 0.0
        if doc.alert_name.lower() == alert_name.lower():
            score += 10.0
        doc_name_tokens = _tokenize(doc.alert_name)
        name_overlap = len(query_tokens & doc_name_tokens)
        if name_overlap:
            score += name_overlap / max(len(query_tokens), 1)
        content_tokens = _tokenize(doc.content)
        content_overlap = len(query_tokens & content_tokens)
        score += 0.1 * content_overlap / max(len(query_tokens), 1)
        return score

    def __len__(self) -> int:
        return len(self._documents)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
