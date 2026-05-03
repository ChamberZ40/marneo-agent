import json

from marneo.tools.core.feishu_tools import (
    feishu_create_doc,
    feishu_search_user,
    feishu_send_file,
    feishu_send_mention,
)


def _enable_local_only():
    from marneo.core.paths import get_config_path

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("privacy:\n  local_only: true\n", encoding="utf-8")


def test_feishu_tools_refuse_in_local_only_mode(tmp_path):
    _enable_local_only()
    local_file = tmp_path / "demo.txt"
    local_file.write_text("demo", encoding="utf-8")

    results = [
        json.loads(feishu_send_mention({"chat_id": "oc_test", "text": "hi"})),
        json.loads(feishu_search_user({"query": "张三"})),
        json.loads(feishu_create_doc({"title": "T"})),
        json.loads(feishu_send_file({"chat_id": "oc_test", "file_path": str(local_file)})),
    ]

    for result in results:
        assert "error" in result
        assert "local-only" in result["error"]
