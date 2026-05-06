import pytest

from marneo.employee.feishu_config import EmployeeFeishuConfig
from marneo.gateway.manager import GatewayManager


@pytest.mark.asyncio
async def test_gateway_manager_passes_employee_feishu_identity_and_policies(monkeypatch):
    captured = {}

    class FakeAdapter:
        platform = "feishu:laoqi"

        def __init__(self, manager, employee_name=None):
            self.manager = manager
            self.employee_name = employee_name

        async def connect(self, config):
            captured.update(config)
            return True

    def fake_load_config(employee_name):
        return EmployeeFeishuConfig(
            employee_name=employee_name,
            app_id="cli_xxx",
            app_secret="dummy",
            domain="feishu",
            bot_open_id="ou_bot",
            bot_user_id="u_bot",
            bot_name="老齐",
            dm_policy="open",
            group_policy="at_only",
        )

    monkeypatch.setattr("marneo.employee.feishu_config.list_configured_employees", lambda: ["laoqi"])
    monkeypatch.setattr("marneo.employee.feishu_config.load_feishu_config", fake_load_config)
    monkeypatch.setattr("marneo.gateway.adapters.feishu.FeishuChannelAdapter", FakeAdapter)
    monkeypatch.setattr("marneo.gateway.config.load_channel_configs", lambda: {})

    manager = GatewayManager()
    await manager.start_all()

    assert captured["bot_open_id"] == "ou_bot"
    assert captured["bot_user_id"] == "u_bot"
    assert captured["bot_name"] == "老齐"
    assert captured["dm_policy"] == "open"
    assert captured["group_policy"] == "at_only"
