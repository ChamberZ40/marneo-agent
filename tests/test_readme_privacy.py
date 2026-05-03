from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_local_only_setup_path():
    text = README.read_text(encoding="utf-8")

    assert "marneo setup local" in text
    assert "privacy.local_only" in text
    assert "Ollama" in text
    assert "marneo work" in text
    assert "外联工具" in text or "external network tools" in text
