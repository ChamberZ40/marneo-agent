from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_local_web_as_loopback_console_not_channel():
    text = README.read_text(encoding="utf-8")

    assert "marneo web" in text
    assert "127.0.0.1:8787" in text
    assert "marneo work" in text
    assert "不是新的外部消息 channel" in text
    assert "--allow-lan" in text


def test_readme_is_english_first_with_chinese_jump_link():
    text = README.read_text(encoding="utf-8")

    assert "[English](#english)" in text
    assert "[中文](#中文)" in text
    assert text.index("## English") < text.index("## 中文")
