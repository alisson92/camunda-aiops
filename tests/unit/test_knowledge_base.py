"""
Testes unitários para knowledge_base.py.

Usa tmp_path do pytest para isolar completamente o sistema de arquivos —
nenhum teste lê ou escreve no data/knowledge real.
"""

import pytest

from knowledge_base import Document, KnowledgeBase, _tokenize


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_splits_camel_case_words(self):
        tokens = _tokenize("ZeebeBackpressureGrowing")
        assert "zeebebackpressuregr" not in tokens  # não divide CamelCase — só alfanumérico
        assert "zeebebackpressuregrowing" in tokens

    def test_splits_on_non_alphanumeric(self):
        tokens = _tokenize("Zeebe-Backpressure_Growing 2026")
        assert "zeebe" in tokens
        assert "backpressure" in tokens
        assert "growing" in tokens
        assert "2026" in tokens

    def test_returns_lowercase(self):
        tokens = _tokenize("ZeebeMemory")
        assert "zeebememory" in tokens
        assert "ZeebeMemory" not in tokens

    def test_empty_string_returns_empty_set(self):
        assert _tokenize("") == set()


# ---------------------------------------------------------------------------
# Document.excerpt
# ---------------------------------------------------------------------------


class TestDocumentExcerpt:
    def test_short_content_returned_in_full(self):
        doc = Document("id", "title", "conteúdo curto", alert_name="Alert")
        assert doc.excerpt(500) == "conteúdo curto"

    def test_long_content_is_truncated(self):
        doc = Document("id", "title", "x" * 600, alert_name="Alert")
        result = doc.excerpt(500)
        assert len(result) < 600
        assert "truncado" in result

    def test_truncation_at_exact_limit(self):
        doc = Document("id", "title", "a" * 500, alert_name="Alert")
        assert doc.excerpt(500) == "a" * 500


# ---------------------------------------------------------------------------
# KnowledgeBase — inicialização e diretórios
# ---------------------------------------------------------------------------


class TestKnowledgeBaseInit:
    def test_creates_directories_on_init(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        assert (tmp_path / "kb" / "runbooks").exists()
        assert (tmp_path / "kb" / "examples").exists()

    def test_empty_kb_has_zero_documents(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        assert len(kb) == 0

    def test_loads_examples_from_directory(self, tmp_path):
        examples_dir = tmp_path / "kb" / "examples"
        examples_dir.mkdir(parents=True)
        (examples_dir / "zeebe-memory.md").write_text(
            "---\nalert_name: ZeebeMemoryPredictedHigh\n---\n# Exemplo\n\nconteúdo",
            encoding="utf-8",
        )
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        assert len(kb) == 1

    def test_loads_runbooks_from_directory(self, tmp_path):
        runbooks_dir = tmp_path / "kb" / "runbooks"
        runbooks_dir.mkdir(parents=True)
        (runbooks_dir / "zeebe-memory-aabbccdd.md").write_text(
            "# Runbook: ZeebeMemoryPredictedHigh\n\nconteúdo",
            encoding="utf-8",
        )
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        assert len(kb) == 1

    def test_loaded_runbook_has_correct_alert_name(self, tmp_path):
        runbooks_dir = tmp_path / "kb" / "runbooks"
        runbooks_dir.mkdir(parents=True)
        (runbooks_dir / "zeebe-memory-aabbccdd.md").write_text(
            "# Runbook: ZeebeMemoryPredictedHigh\n\nconteúdo",
            encoding="utf-8",
        )
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        doc = list(kb._documents.values())[0]
        assert doc.alert_name == "ZeebeMemoryPredictedHigh"

    def test_loaded_example_has_correct_alert_name_from_frontmatter(self, tmp_path):
        examples_dir = tmp_path / "kb" / "examples"
        examples_dir.mkdir(parents=True)
        (examples_dir / "zeebe-memory.md").write_text(
            "---\nalert_name: ZeebeMemoryPredictedHigh\n---\n# Título\n\nconteúdo",
            encoding="utf-8",
        )
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        doc = kb._documents["example-zeebe-memory"]
        assert doc.alert_name == "ZeebeMemoryPredictedHigh"
        assert doc.source == "curated"

    def test_example_without_frontmatter_infers_name_from_filename(self, tmp_path):
        examples_dir = tmp_path / "kb" / "examples"
        examples_dir.mkdir(parents=True)
        (examples_dir / "zeebe-memory-predicted-high.md").write_text(
            "# Título\n\nconteúdo sem frontmatter",
            encoding="utf-8",
        )
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        doc = kb._documents["example-zeebe-memory-predicted-high"]
        # Heurística: CamelCase dos tokens do filename
        assert doc.alert_name == "ZeebeMemoryPredictedHigh"


# ---------------------------------------------------------------------------
# KnowledgeBase — add_document e persistência
# ---------------------------------------------------------------------------


class TestKnowledgeBaseAddDocument:
    def test_add_document_increases_count(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("doc-1", "Título", "conteúdo", alert_name="ZeebeAlert")
        assert len(kb) == 1

    def test_generated_document_is_persisted_to_disk(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("runbook-abc12345", "Título", "# Runbook\n\nconteúdo", alert_name="ZeebeAlert")
        assert (tmp_path / "kb" / "runbooks" / "runbook-abc12345.md").exists()

    def test_persisted_content_matches(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("runbook-abc12345", "Título", "# conteúdo especial", alert_name="ZeebeAlert")
        content = (tmp_path / "kb" / "runbooks" / "runbook-abc12345.md").read_text()
        assert "# conteúdo especial" in content

    def test_curated_document_is_not_persisted_to_disk(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("example-zeebe", "Título", "conteúdo", alert_name="ZeebeAlert", source="curated")
        assert not (tmp_path / "kb" / "runbooks" / "example-zeebe.md").exists()

    def test_overwrite_existing_document(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("doc-1", "Título", "v1", alert_name="ZeebeAlert")
        kb.add_document("doc-1", "Título", "v2", alert_name="ZeebeAlert")
        assert kb._documents["doc-1"].content == "v2"


# ---------------------------------------------------------------------------
# KnowledgeBase — search
# ---------------------------------------------------------------------------


class TestKnowledgeBaseSearch:
    def test_empty_kb_returns_empty_list(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        assert kb.search("ZeebeMemoryPredictedHigh") == []

    def test_exact_match_returns_document(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("doc-1", "Runbook: ZeebeMemory", "conteúdo", alert_name="ZeebeMemoryPredictedHigh")
        results = kb.search("ZeebeMemoryPredictedHigh")
        assert len(results) == 1
        assert results[0].alert_name == "ZeebeMemoryPredictedHigh"

    def test_unrelated_alert_returns_empty(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("doc-1", "Título", "conteúdo", alert_name="NodeDiskPressure")
        results = kb.search("ZeebeMemoryPredictedHigh")
        assert results == []

    def test_partial_match_scores_lower_than_exact(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document("exact", "Título", "x", alert_name="ZeebeMemoryPredictedHigh")
        kb.add_document("partial", "Título", "x", alert_name="ZeebeBackpressureGrowing")
        results = kb.search("ZeebeMemoryPredictedHigh", k=2)
        assert results[0].doc_id == "exact"

    def test_respects_k_limit(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        for i in range(5):
            kb.add_document(f"doc-{i}", f"Runbook {i}", "x", alert_name="ZeebeMemoryPredictedHigh")
        results = kb.search("ZeebeMemoryPredictedHigh", k=2)
        assert len(results) == 2

    def test_case_insensitive_exact_match(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        # doc com alert_name em minúsculas deve ser encontrado por query em CamelCase
        kb.add_document("doc-1", "Título", "conteúdo", alert_name="zeebememorypredicted")
        results = kb.search("ZeebeMemoryPredicted")
        assert len(results) == 1
        # e vice-versa
        kb2 = KnowledgeBase(data_dir=tmp_path / "kb2")
        kb2.add_document("doc-2", "Título", "conteúdo", alert_name="ZeebeMemoryPredicted")
        results2 = kb2.search("zeebememorypredicted")
        assert len(results2) == 1

    def test_content_token_overlap_scores_document(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        # O tokenizador não divide CamelCase — "ZeebeMemory" vira um único token.
        # Content overlap funciona quando o conteúdo contém o token exato lowercased.
        kb.add_document("doc-1", "Título", "zeebememory critical heap", alert_name="OutroAlerta")
        results = kb.search("ZeebeMemory", k=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# KnowledgeBase — helpers de parsing
# ---------------------------------------------------------------------------


class TestKnowledgeBaseHelpers:
    def test_extract_title_from_heading(self):
        content = "# Meu Título\n\nconteúdo"
        assert KnowledgeBase._extract_title(content) == "Meu Título"

    def test_extract_title_no_heading_returns_empty(self):
        assert KnowledgeBase._extract_title("sem heading aqui") == ""

    def test_extract_alert_name_from_frontmatter(self):
        content = "---\nalert_name: ZeebeMemoryPredictedHigh\n---\n# Título"
        assert KnowledgeBase._extract_alert_name(content, "stem") == "ZeebeMemoryPredictedHigh"

    def test_extract_alert_name_falls_back_to_stem(self):
        result = KnowledgeBase._extract_alert_name("sem frontmatter", "zeebe-memory-predicted-high")
        assert result == "ZeebeMemoryPredictedHigh"

    def test_extract_alert_name_from_runbook_heading(self):
        content = "# Runbook: ZeebeBackpressureGrowing\n\nconteúdo"
        assert KnowledgeBase._extract_alert_name_from_runbook(content) == "ZeebeBackpressureGrowing"

    def test_extract_alert_name_from_runbook_no_heading(self):
        assert KnowledgeBase._extract_alert_name_from_runbook("sem heading") == ""


# ---------------------------------------------------------------------------
# KnowledgeBase — persistência e reload
# ---------------------------------------------------------------------------


class TestKnowledgeBasePersistence:
    def test_runbook_survives_reload(self, tmp_path):
        kb1 = KnowledgeBase(data_dir=tmp_path / "kb")
        kb1.add_document(
            "runbook-abc12345",
            "Runbook: ZeebeMemoryPredictedHigh",
            "# Runbook: ZeebeMemoryPredictedHigh\n\nconteúdo",
            alert_name="ZeebeMemoryPredictedHigh",
        )
        # Nova instância lê do disco
        kb2 = KnowledgeBase(data_dir=tmp_path / "kb")
        assert len(kb2) == 1
        results = kb2.search("ZeebeMemoryPredictedHigh")
        assert results[0].alert_name == "ZeebeMemoryPredictedHigh"


# ---------------------------------------------------------------------------
# KnowledgeBase — get_runbooks
# ---------------------------------------------------------------------------


class TestKnowledgeBaseGetRunbooks:
    def test_get_runbooks_empty_when_no_generated(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        assert kb.get_runbooks() == {}

    def test_get_runbooks_returns_generated_document(self, tmp_path):
        kb = KnowledgeBase(data_dir=tmp_path / "kb")
        kb.add_document(
            "rb-abc12345",
            "Runbook: ZeebeMemoryPredictedHigh",
            "# Runbook: ZeebeMemoryPredictedHigh\n\nconteúdo",
            alert_name="ZeebeMemoryPredictedHigh",
            source="generated",
        )
        result = kb.get_runbooks()
        assert "rb-abc12345" in result
        assert result["rb-abc12345"].source == "generated"
        assert result["rb-abc12345"].alert_name == "ZeebeMemoryPredictedHigh"

    def test_get_runbooks_excludes_curated_documents(self, tmp_path):
        kb_dir = tmp_path / "kb"
        examples_dir = kb_dir / "examples"
        examples_dir.mkdir(parents=True)
        (examples_dir / "zeebe-alert.md").write_text(
            "---\nalert_name: ZeebeAlert\n---\n# Exemplo\nconteúdo"
        )
        kb = KnowledgeBase(data_dir=kb_dir)
        # Apenas o curated foi carregado — get_runbooks não deve retorná-lo
        assert kb.get_runbooks() == {}

    def test_get_runbooks_survives_reload(self, tmp_path):
        kb1 = KnowledgeBase(data_dir=tmp_path / "kb")
        kb1.add_document(
            "rb-reload-00",
            "Runbook: TestAlert",
            "# Runbook: TestAlert\n\nconteúdo",
            alert_name="TestAlert",
        )
        # Após reload do disco, get_runbooks deve reconhecer o runbook persistido
        kb2 = KnowledgeBase(data_dir=tmp_path / "kb")
        runbooks = kb2.get_runbooks()
        assert "rb-reload-00" in runbooks
