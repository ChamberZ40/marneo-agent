from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
README_CN = ROOT / "README_CN.md"


def test_readme_documents_local_only_setup_path():
    text = README.read_text(encoding="utf-8")

    assert "marneo setup local" in text
    assert "privacy" in text.lower()
    assert "marneo work" in text
    assert "external network tools" in text or "external-tool gating" in text


def test_readme_cn_documents_local_only_setup_path():
    text = README_CN.read_text(encoding="utf-8")

    assert "marneo setup local" in text
    assert "privacy.local_only" in text or "local_only: true" in text
    assert "外联工具" in text
