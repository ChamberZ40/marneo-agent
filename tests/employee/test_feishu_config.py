from marneo.employee import feishu_config as fc


def test_feishu_config_round_trip_preserves_identity_and_policies(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "get_employees_dir", lambda: tmp_path / "employees")

    cfg = fc.EmployeeFeishuConfig(
        employee_name="laoqi",
        app_id="cli_xxx",
        app_secret="dummy",
        domain="feishu",
        bot_open_id="ou_bot",
        bot_user_id="u_bot",
        bot_name="老齐",
        dm_policy="open",
        group_policy="at_only",
        team_chat_id="oc_team",
    )

    fc.save_feishu_config(cfg)
    loaded = fc.load_feishu_config("laoqi")

    assert loaded is not None
    assert loaded.bot_open_id == "ou_bot"
    assert loaded.bot_user_id == "u_bot"
    assert loaded.bot_name == "老齐"
    assert loaded.dm_policy == "open"
    assert loaded.group_policy == "at_only"
    assert loaded.team_chat_id == "oc_team"


def test_feishu_config_loads_old_files_with_safe_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "get_employees_dir", lambda: tmp_path / "employees")
    path = tmp_path / "employees" / "laoqi" / "feishu.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "app_id: cli_xxx\napp_secret: dummy\ndomain: feishu\nbot_open_id: ou_bot\n",
        encoding="utf-8",
    )

    loaded = fc.load_feishu_config("laoqi")

    assert loaded is not None
    assert loaded.bot_open_id == "ou_bot"
    assert loaded.bot_user_id == ""
    assert loaded.bot_name == ""
    assert loaded.dm_policy == "open"
    assert loaded.group_policy == "at_only"
