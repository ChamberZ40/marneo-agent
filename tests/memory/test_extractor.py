# tests/memory/test_extractor.py
from marneo.memory.extractor import extract_episode


def test_extracts_decision():
    ep = extract_episode(
        "用哪个库处理 PDF？",
        "我们决定用 pypdf 而不是 pdfminer，因为 API 更简单。"
    )
    assert ep is not None
    assert ep.type == "decision"
    assert "pypdf" in ep.content


def test_extracts_discovery():
    ep = extract_episode(
        "为什么 pandas 读取出错？",
        "发现是 UTF-8 编码问题，用 encoding='utf-8-sig' 解决了。"
    )
    assert ep is not None
    assert ep.type == "discovery"


def test_skips_short_reply():
    ep = extract_episode("你好", "你好！")
    assert ep is None


def test_skips_no_signal():
    ep = extract_episode("怎么样？", "好的，我明白了。这个任务完成了。")
    assert ep is None


def test_extracts_preference():
    ep = extract_episode(
        "代码风格？",
        "始终用 Python，不用 JavaScript。所有函数要有类型注解。约定是这样的。"
    )
    assert ep is not None
    assert ep.type == "preference"
