from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
README_CN = ROOT / "README_CN.md"


def test_readme_documents_local_web_as_loopback_console_not_channel():
    text = README.read_text(encoding="utf-8")

    assert "marneo web" in text
    assert "127.0.0.1:8787" in text
    assert "marneo work" in text
    # English README states it is not a new external messaging channel
    assert "not a new external messaging channel" in text


def test_readme_cn_documents_local_web_as_loopback_console_not_channel():
    text = README_CN.read_text(encoding="utf-8")

    assert "marneo web" in text
    assert "127.0.0.1:8787" in text
    assert "不是新的外部消息 channel" in text
    assert "--allow-lan" in text


def test_readme_is_english_only_with_chinese_link():
    text = README.read_text(encoding="utf-8")

    # README.md links to README_CN.md for Chinese
    assert "[中文](README_CN.md)" in text
    # No Chinese h2 section in README.md
    assert "## 中文" not in text


def test_readme_cn_links_back_to_english():
    text = README_CN.read_text(encoding="utf-8")

    assert "[English](README.md)" in text
