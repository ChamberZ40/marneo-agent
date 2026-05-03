from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_changed_files_do_not_contain_obvious_secrets():
    paths = [
        "README.md",
        "marneo/cli/setup_cmd.py",
        "marneo/core/config.py",
        "marneo/engine/provider.py",
        "marneo/tools/core/ask_user.py",
        "marneo/tools/core/feishu_tools.py",
        "marneo/tools/core/lark_cli.py",
        "marneo/tools/core/web.py",
        "marneo/tools/loader.py",
        "marneo/tools/mcp_bridge.py",
        "marneo/tools/registry.py",
        "tests/test_config_privacy.py",
        "tests/test_readme_privacy.py",
        "tests/test_secret_scan_changed_files.py",
        "tests/tools/test_feishu_privacy.py",
        "tests/tools/test_loader_privacy.py",
    ]
    text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)

    forbidden_literals = [
        "-----BEGIN " + "PRIVATE KEY-----",
        "Authorization: Bearer " + "sk-",
        "app_" + "secret: cli_",
        "access_" + "token: u-",
        "refresh_" + "token: u-",
    ]

    for literal in forbidden_literals:
        assert literal not in text
