## 1. 测试框架搭建

- [ ] 1.1 `pyproject.toml` 添加 pytest、pytest-cov、pytest-asyncio 依赖（dev group）
- [ ] 1.2 创建 `tests/` 目录结构：`tests/employee/`、`tests/project/`、`tests/gateway/`
- [ ] 1.3 配置 `pytest.ini`（testpaths、asyncio_mode=auto）和 `tests/conftest.py`（共享 fixtures）

## 2. 核心模块单元测试

- [ ] 2.1 `tests/employee/test_profile.py`：create / load / save / increment_xp
- [ ] 2.2 `tests/employee/test_growth.py`：should_level_up / next_level / xp_thresholds
- [ ] 2.3 `tests/employee/test_reports.py`：append / get / list（mock 文件系统）
- [ ] 2.4 `tests/project/test_workspace.py`：create / load / assign_employee
- [ ] 2.5 `tests/project/test_skills.py`：save / list / build_context
- [ ] 2.6 `tests/gateway/test_manager.py`：dedup 逻辑 / dispatch 路由 / session 隔离

## 3. 类型注解补全

- [ ] 3.1 `marneo/core/` — 补全所有函数返回类型（`config.py`、`paths.py`）
- [ ] 3.2 `marneo/employee/` — 补全参数和返回类型（`profile.py`、`growth.py`、`reports.py`）
- [ ] 3.3 `marneo/project/` — 补全 `workspace.py`、`skills.py`
- [ ] 3.4 `marneo/gateway/` — 补全 `manager.py`、`session.py`、`base.py`
- [ ] 3.5 `pyproject.toml` 添加 pyright basic 配置；CI 步骤运行 `pyright`

## 4. 结构化日志

- [ ] 4.1 创建 `marneo/core/logging.py`：`get_logger(name, **context)` factory，输出带 context 字段的 structlog / stdlib JSON 日志
- [ ] 4.2 `marneo/gateway/manager.py` 改用结构化 log（含 `platform`、`chat_id`、`employee_name`）
- [ ] 4.3 `marneo/employee/interview.py` 改用结构化 log（含 `employee_name`、`question_index`）

## 5. 输入验证

- [ ] 5.1 `marneo/core/config.py`：`load_config()` 使用 pydantic / dataclasses 校验，失败时打印具体缺失字段
- [ ] 5.2 CLI 命令参数验证：`app_id` 格式（`cli_`/`tt_` 前缀）、model 名称白名单
