# 团队协作接入 marneo work Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 multi-employee-team 的协调者逻辑接入 `marneo work`，使协调者员工在对话中自动识别复杂任务、并行调度专员 ChatSession、汇总回复用户。

**Architecture:** CLI 模式下，协调者和各专员共享同一进程，通过 `asyncio.gather` 并行运行独立的 ChatSession；TUI 展示团队工作进度；team 检测逻辑在每条消息的 `on_input` 中执行。Feishu @mention 路由为 Gateway 模式的未来扩展点。

**Tech Stack:** Python 3.11+, asyncio, ChatSession（已有），TeamConfig（已有），coordinator.py（已有）

---

## Task 1: 扩展 coordinator.py — 进程内并行专员执行

**Files:**
- Modify: `marneo/collaboration/coordinator.py`

### Step 1: 在 `coordinator.py` 末尾添加 `run_team_session()` 函数

```python
async def run_team_session(
    user_message: str,
    team_config: "TeamConfig",
    coordinator_engine: Any,
    progress_cb: Any = None,
) -> str:
    """Orchestrate parallel specialist sessions and aggregate results.

    Args:
        user_message: Original user request
        team_config: Team configuration (coordinator, members, roles)
        coordinator_engine: Coordinator's ChatSession for splitting + aggregating
        progress_cb: Optional async callback(msg: str) for TUI progress display

    Returns:
        Aggregated final reply string
    """
    from marneo.employee.profile import load_profile

    specialists = team_config.specialists
    if not specialists:
        return ""

    async def _notify(msg: str) -> None:
        if progress_cb:
            try:
                await progress_cb(msg)
            except Exception:
                pass

    # ── Step 1: Split task ────────────────────────────────────────────
    await _notify(f"🔀 协调者正在拆分任务（{len(specialists)} 位专员）...")
    assignments = await split_task_for_specialists(
        user_message, specialists, coordinator_engine
    )

    if not assignments:
        return ""

    # ── Step 2: Run specialist sessions in parallel ───────────────────
    from marneo.engine.chat import ChatSession

    async def _run_specialist(member: Any) -> tuple[str, str]:
        """Run one specialist's ChatSession for their sub-task."""
        emp_name = member.employee
        sub_task = assignments.get(emp_name, user_message)

        await _notify(f"⚡ {emp_name}（{member.role}）开始处理...")

        # Build specialist system prompt from their SOUL.md if available
        profile = load_profile(emp_name)
        system = f"你是 {emp_name}，{member.role}。专注处理分配给你的子任务。"
        if profile and profile.soul_path.exists():
            soul = profile.soul_path.read_text(encoding="utf-8").strip()
            system = f"{soul}\n\n{system}"

        session = ChatSession(system_prompt=system)
        parts: list[str] = []
        try:
            async for event in session.send(sub_task):
                if event.type == "text" and event.content:
                    parts.append(event.content)
        except Exception as e:
            log.error("[Team] specialist %s error: %s", emp_name, e)
            parts = [f"（{emp_name} 处理出错：{e}）"]

        reply = "".join(parts).strip()
        await _notify(f"✓ {emp_name} 完成")
        return emp_name, reply

    # Parallel execution
    tasks = [_run_specialist(m) for m in specialists]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, str] = {}
    for item in results_list:
        if isinstance(item, tuple):
            emp_name, reply = item
            results[emp_name] = reply

    if not results:
        return ""

    # ── Step 3: Aggregate ─────────────────────────────────────────────
    await _notify("🔗 协调者正在汇总结果...")
    final = await aggregate_results(user_message, results, coordinator_engine)
    return final
```

### Step 2: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.collaboration.coordinator import run_team_session
import inspect
src = inspect.getsource(run_team_session)
assert 'asyncio.gather' in src
assert 'aggregate_results' in src
print('run_team_session OK')
"
```

### Step 3: Commit

```bash
git add marneo/collaboration/coordinator.py
git commit -m "feat(team): add run_team_session() for in-process parallel specialist execution"
```

---

## Task 2: 更新 `marneo/cli/work.py` — 团队模式接入

**Files:**
- Modify: `marneo/cli/work.py`

### Step 1: 在 `_work_loop` 里的 `session` 变量定义之后，添加团队检测帮助函数

在 `_work_loop` 顶部（`session = ChatSession(...)` 之后）添加：

```python
    # ── Team detection ────────────────────────────────────────────────
    from marneo.collaboration.team import load_team_config  # type: ignore[import]
    from marneo.collaboration.coordinator import should_use_team, run_team_session  # type: ignore[import]
    from marneo.project.workspace import get_employee_projects  # type: ignore[import]

    def _get_coordinator_team() -> "TeamConfig | None":
        """Return team config if this employee is a coordinator with team."""
        try:
            projects = get_employee_projects(employee_name)
            for proj in projects:
                team = load_team_config(proj.name)
                if team and team.coordinator == employee_name and team.is_configured():
                    return team
        except Exception:
            pass
        return None

    _active_team = _get_coordinator_team()
```

### Step 2: 替换 `on_input` 的正常消息处理区块

找到：
```python
        tui.print(f"  {_DIM}You › {text}{_RST}")
        display.reset()

        async for event in session.send(text):
```

替换为：

```python
        tui.print(f"  {_DIM}You › {text}{_RST}")
        display.reset()

        # ── Team mode: parallel specialist execution ──────────────────
        if _active_team and not cmd.startswith("/"):
            try:
                use_team = await should_use_team(text, len(_active_team.members))
            except Exception:
                use_team = False

            if use_team:
                _team_reply = await _run_with_team(
                    text, _active_team, session, tui, display
                )
                if _team_reply:
                    # Post-turn tracking with team reply
                    try:
                        from marneo.employee.profile import increment_conversation  # type: ignore[import]
                        from marneo.employee.reports import append_daily_entry  # type: ignore[import]
                        increment_conversation(employee_name)
                        summary = _team_reply[:60].replace("\n", " ")
                        append_daily_entry(employee_name, f"[Team] {text[:40]} → {summary}", tag="协作")
                    except Exception:
                        pass
                    return

        # ── Solo mode (default) ───────────────────────────────────────
        async for event in session.send(text):
```

### Step 3: 在 `_work_loop` 之前添加 `_run_with_team` 辅助函数

在文件中的 `async def _work_loop` 之前插入：

```python
async def _run_with_team(
    text: str,
    team: Any,
    session: Any,
    tui: Any,
    display: Any,
) -> str:
    """Execute a task in team mode: split → parallel specialists → aggregate → display."""
    from marneo.collaboration.coordinator import run_team_session

    _PRI  = "\033[1;38;2;255;102;17m"
    _DIM  = "\033[38;2;85;85;85m"
    _NEON = "\033[38;2;0;255;204m"
    _RST  = "\033[0m"

    # Show team banner
    member_str = " + ".join(
        f"{m.employee}({m.role or '专员'})" for m in team.members
    )
    tui.print(f"\n  {_PRI}◆ 团队模式启动{_RST}  {_DIM}{member_str}{_RST}")

    async def _progress(msg: str) -> None:
        tui.print(f"  {_DIM}{msg}{_RST}")

    final_reply = await run_team_session(
        user_message=text,
        team_config=team,
        coordinator_engine=session,
        progress_cb=_progress,
    )

    if final_reply:
        # Display aggregated result via StreamDisplay
        display.reset()
        # Feed as chunked text to get markdown rendering
        for chunk in [final_reply[i:i+80] for i in range(0, len(final_reply), 80)]:
            display.on_text(chunk)
        display.finish()

    return final_reply
```

### Step 4: 验证

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "
from marneo.cli.work import cmd_work, work_app, _run_with_team
import inspect
src = inspect.getsource(work_app.registered_callback.callback)
print('_run_with_team imported OK')
print('work.py team integration OK')
"
marneo work --help
```

### Step 5: Commit

```bash
git add marneo/cli/work.py
git commit -m "feat(team): wire team collaboration into marneo work (parallel specialist sessions)"
```

---

## Task 3: 单元测试

**Files:**
- Create: `tests/collaboration/test_coordinator.py`
- Create: `tests/collaboration/__init__.py`

### Step 1: 创建测试文件

```python
# tests/collaboration/test_coordinator.py
"""Tests for team coordinator logic."""
import asyncio
import pytest
from marneo.collaboration.coordinator import should_use_team, aggregate_results
from marneo.collaboration.team import TeamConfig, TeamMember


def test_should_use_team_complex_task():
    result = asyncio.run(should_use_team("帮我综合分析数据并制定详细的营销计划", 2))
    assert result is True


def test_should_use_team_simple_task():
    result = asyncio.run(should_use_team("hi", 2))
    assert result is False


def test_should_use_team_single_member():
    # Team with < 2 members should not trigger team mode
    result = asyncio.run(should_use_team("复杂的综合分析任务", 1))
    assert result is False


def test_team_config_specialists():
    config = TeamConfig(
        project_name="test",
        coordinator="GAI",
        members=[
            TeamMember("GAI", "协调者"),
            TeamMember("ARIA", "专员"),
            TeamMember("BOB", "专员"),
        ],
    )
    specs = config.specialists
    assert len(specs) == 2
    assert all(m.employee != "GAI" for m in specs)


def test_team_config_is_configured():
    config = TeamConfig(
        project_name="test",
        coordinator="GAI",
        members=[TeamMember("GAI", "协调者"), TeamMember("ARIA", "专员")],
    )
    assert config.is_configured()


def test_team_config_not_configured_single():
    config = TeamConfig(project_name="test", coordinator="GAI",
                        members=[TeamMember("GAI", "协调者")])
    assert not config.is_configured()


def test_team_config_not_configured_no_coordinator():
    config = TeamConfig(project_name="test",
                        members=[TeamMember("A", ""), TeamMember("B", "")])
    assert not config.is_configured()
```

### Step 2: 运行测试

```bash
cd /Users/chamber/code/marneo-agent
pytest tests/collaboration/ -v -q
```
Expected: `7 passed`

### Step 3: Commit

```bash
git add tests/collaboration/
git commit -m "test(team): add coordinator and team config unit tests"
```

---

## Task 4: 最终集成验证

### Step 1: 全量测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
print('=== 团队协作集成验证 ===')

# 1. 模块导入
from marneo.collaboration.coordinator import run_team_session, should_use_team, aggregate_results
from marneo.collaboration.team import TeamConfig, TeamMember, save_team_config, load_team_config
from marneo.cli.work import _run_with_team, work_app
print('✓ 所有模块导入 OK')

# 2. 团队配置
from marneo.project.workspace import create_project
import shutil, asyncio

p = create_project('team-test-final')
config = TeamConfig(
    project_name='team-test-final',
    coordinator='GAI',
    team_chat_id='oc_xxx',
    members=[TeamMember('GAI', '协调者'), TeamMember('ARIA', '数据分析')],
)
save_team_config(config)
loaded = load_team_config('team-test-final')
assert loaded.is_configured() and loaded.coordinator == 'GAI'
print('✓ 团队配置 OK')

# 3. 复杂任务判断
r1 = asyncio.run(should_use_team('帮我综合分析并制定详细计划', 2))
r2 = asyncio.run(should_use_team('hi', 1))
assert r1 is True and r2 is False
print('✓ 任务复杂度判断 OK')

# 4. run_team_session 结构验证
import inspect
src = inspect.getsource(run_team_session)
assert 'asyncio.gather' in src and 'aggregate_results' in src
print('✓ run_team_session 结构 OK')

# 5. work.py team 集成
src2 = open('marneo/cli/work.py').read()
assert '_active_team' in src2 and '_run_with_team' in src2
print('✓ work.py team 集成 OK')

shutil.rmtree(p.directory)
print()
print('ALL CHECKS PASSED')
"
```

### Step 2: 运行完整测试套件

```bash
pytest tests/ -q --tb=short
```
Expected: All tests pass (≥37 tests)

### Step 3: 最终提交

```bash
git log --oneline -5
```
