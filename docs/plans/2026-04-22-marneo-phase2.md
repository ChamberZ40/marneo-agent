# Marneo Agent Phase 2 — Employee System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现完整的员工系统：`marneo hire`（LLM 面试入职）、员工档案管理、四级成长体系、`marneo work [employee]` 选员工对话、日报/周报/月报自动生成。

**Architecture:** 员工数据存 `~/.marneo/employees/<name>/`（YAML，不用 SQLite），支持多员工并行。LLM 面试引擎从 flaming-warkhorse `identity_interview.py` 精简迁移。每轮对话后自动追加日报条目，报告可以 `marneo report daily` 查看。

**Tech Stack:** Python 3.11+, pyyaml, anthropic/openai SDK（已有）, typer, rich, prompt-toolkit

**Reference:**
- `/Users/chamber/code/flaming-warkhorse/flaming_warhorse/employee/` — 迁移参考
- `/Users/chamber/code/marneo-agent/` — 当前 marneo 项目

---

## Task 1: Employee 数据模型

**Files:**
- Create: `marneo/employee/__init__.py`
- Create: `marneo/employee/profile.py`

### Step 1: 创建 `marneo/employee/__init__.py`（空文件）

### Step 2: 创建 `marneo/employee/profile.py`

```python
# marneo/employee/profile.py
"""Employee profile — stored as YAML under ~/.marneo/employees/<name>/

Directory layout:
  ~/.marneo/employees/
  └── GAI/
      ├── profile.yaml      # level, hired_at, personality, domains, style
      ├── SOUL.md           # 身份（hire 面试生成，永久）
      └── reports/
          ├── daily/
          ├── weekly/
          └── monthly/
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_employees_dir

LEVEL_INTERN  = "实习生"
LEVEL_JUNIOR  = "初级员工"
LEVEL_MID     = "中级员工"
LEVEL_SENIOR  = "高级员工"
LEVEL_ORDER   = [LEVEL_INTERN, LEVEL_JUNIOR, LEVEL_MID, LEVEL_SENIOR]


@dataclass
class EmployeeProfile:
    name: str
    level: str = LEVEL_INTERN
    hired_at: str = ""
    personality: str = ""
    domains: str = ""
    style: str = ""
    # per-level achievement counters
    level_conversations: int = 0
    level_skills: int = 0
    total_conversations: int = 0

    @property
    def is_intern(self) -> bool:
        return self.level == LEVEL_INTERN

    @property
    def directory(self) -> Path:
        d = get_employees_dir() / self.name
        d.mkdir(exist_ok=True)
        return d

    @property
    def soul_path(self) -> Path:
        return self.directory / "SOUL.md"

    @property
    def reports_dir(self) -> Path:
        d = self.directory / "reports"
        d.mkdir(exist_ok=True)
        return d


def list_employees() -> list[str]:
    """Return names of all configured employees."""
    d = get_employees_dir()
    return sorted(
        p.name for p in d.iterdir()
        if p.is_dir() and (p / "profile.yaml").exists()
    )


def load_profile(name: str) -> EmployeeProfile | None:
    """Load employee profile from YAML. Returns None if not found."""
    path = get_employees_dir() / name / "profile.yaml"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return EmployeeProfile(
            name=name,
            level=data.get("level", LEVEL_INTERN),
            hired_at=data.get("hired_at", ""),
            personality=data.get("personality", ""),
            domains=data.get("domains", ""),
            style=data.get("style", ""),
            level_conversations=int(data.get("level_conversations", 0)),
            level_skills=int(data.get("level_skills", 0)),
            total_conversations=int(data.get("total_conversations", 0)),
        )
    except Exception:
        return None


def save_profile(profile: EmployeeProfile) -> Path:
    """Save employee profile to YAML. Returns the profile.yaml path."""
    profile.directory.mkdir(parents=True, exist_ok=True)
    path = profile.directory / "profile.yaml"
    data = {
        "name": profile.name,
        "level": profile.level,
        "hired_at": profile.hired_at,
        "personality": profile.personality,
        "domains": profile.domains,
        "style": profile.style,
        "level_conversations": profile.level_conversations,
        "level_skills": profile.level_skills,
        "total_conversations": profile.total_conversations,
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def create_employee(
    name: str,
    personality: str = "",
    domains: str = "",
    style: str = "",
) -> EmployeeProfile:
    """Create and save a new employee profile."""
    hired_at = datetime.now(timezone.utc).isoformat()
    profile = EmployeeProfile(
        name=name,
        level=LEVEL_INTERN,
        hired_at=hired_at,
        personality=personality,
        domains=domains,
        style=style,
    )
    save_profile(profile)
    return profile


def increment_conversation(name: str) -> EmployeeProfile | None:
    """Increment conversation counters. Call after each completed turn."""
    profile = load_profile(name)
    if not profile:
        return None
    from dataclasses import replace
    updated = replace(
        profile,
        level_conversations=profile.level_conversations + 1,
        total_conversations=profile.total_conversations + 1,
    )
    save_profile(updated)
    return updated
```

### Step 3: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.employee.profile import (
    create_employee, load_profile, save_profile, list_employees, increment_conversation,
    LEVEL_INTERN, LEVEL_ORDER
)
p = create_employee('TestEmp', personality='务实干练', domains='编程', style='简洁')
assert p.name == 'TestEmp' and p.level == LEVEL_INTERN
loaded = load_profile('TestEmp')
assert loaded.personality == '务实干练'
updated = increment_conversation('TestEmp')
assert updated.total_conversations == 1
names = list_employees()
assert 'TestEmp' in names
print('ALL OK, employees:', names)
# cleanup
import shutil; shutil.rmtree(p.directory)
"
```

### Step 4: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/employee/
git commit -m "feat: add employee data model (YAML-based, multi-employee)"
```

---

## Task 2: LLM 面试引擎

**Files:**
- Create: `marneo/employee/interview.py`

### Step 1: 创建 `marneo/employee/interview.py`

精简迁移自 flaming-warkhorse `identity_interview.py`，保留动态一问一答逻辑：

```python
# marneo/employee/interview.py
"""LLM-driven interview engine for marneo hire.

Interview loop:
  1. Send full conversation history to LLM
  2. LLM returns a question OR ##DONE##
  3. User answers; append to history
  4. Repeat until ##DONE## or MAX_ROUNDS
  5. Final LLM call synthesizes SOUL.md
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
MIN_ROUNDS = 5

_INTERVIEWER_SYSTEM = """\
你是一位资深的数字员工档案顾问，正在对一名新入职的数字员工进行入职深度访谈。
你的目标是通过对话收集足够的信息，最终生成这名员工的 SOUL.md 身份档案。

访谈规则：
- 每次只问一个问题，简短有力
- 根据前面的回答动态调整问题方向
- 前 {min_rounds} 轮必须继续；之后如果信息足够，输出 ##DONE##
- 问题要覆盖：价值观/性格/热情/工作哲学/与用户相处方式
- 每个问题附带 3-4 个选项（字母编号），允许追加自由回答

格式（严格遵守）：
问题文本

A. 选项一
B. 选项二
C. 选项三
D. 其他（请自行描述）

只输出问题+选项（或 ##DONE##），不要任何前缀。
"""

_SOUL_SYSTEM = """\
你是一位精通人物传记的写作专家。
根据以下访谈记录，为这名数字员工撰写 SOUL.md 私人自述。

访谈记录：
{qa_content}

要求：
1. 用第一人称，语气真实有温度，200-350 字，像写给用户的信
2. 融合访谈内容自然叙述，不要直接引用问题
3. 末尾一行是标志性口头禅（10 字以内，加 > 引用格式）

直接输出内容，不要任何前缀或标题。
"""


def _call_llm(messages: list[dict], *, system: str, max_tokens: int = 800) -> str:
    """Synchronous LLM call. Returns text content."""
    import os, anthropic
    from marneo.core.config import load_config

    cfg = load_config()
    if cfg.provider and cfg.provider.api_key:
        api_key = cfg.provider.api_key
        base_url = cfg.provider.base_url or None
        model = cfg.provider.model or "claude-haiku-4-5-20251001"
        protocol = cfg.provider.protocol
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = None
        model = "claude-haiku-4-5-20251001"
        protocol = "anthropic-compatible"

    if protocol == "openai-compatible":
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            system=system if not messages else None,
            messages=[{"role": "system", "content": system}] + messages if messages else messages,
        )
        # Actually for openai we pass system in messages
        all_msgs = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(model=model, max_tokens=max_tokens, messages=all_msgs)
        for block in resp.choices[0].message.content if hasattr(resp.choices[0].message, 'content') else []:
            pass
        content = resp.choices[0].message.content or ""
        return content.strip()
    else:
        client = anthropic.Anthropic(api_key=api_key, **({"base_url": base_url} if base_url else {}))
        msg = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
        for block in msg.content:
            if hasattr(block, "text"):
                return block.text.strip()
        return ""


def next_question(history: list[dict], round_number: int) -> str | None:
    """Ask LLM for next interview question. Returns None when done."""
    system = _INTERVIEWER_SYSTEM.format(min_rounds=MIN_ROUNDS)
    msgs = history if history else [{"role": "user", "content": "请开始面试，提出第一个问题。"}]
    try:
        response = _call_llm(msgs, system=system, max_tokens=300)
    except Exception as e:
        log.error("Interview LLM error: %s", e)
        return None
    if "##DONE##" in response or round_number >= MAX_ROUNDS:
        return None
    return response.replace("##DONE##", "").strip() or None


def parse_question(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """Parse 'question\\nA. opt1\\nB. opt2' into (question_text, [(letter, text)])."""
    lines = [l.rstrip() for l in raw.strip().splitlines()]
    options: list[tuple[str, str]] = []
    question_lines: list[str] = []
    in_options = False
    for line in lines:
        stripped = line.strip()
        if (len(stripped) >= 3 and stripped[0].isupper()
                and stripped[1] in ".、)" and stripped[2] == " "):
            in_options = True
            options.append((stripped[0], stripped[3:].strip()))
        elif not in_options and stripped:
            question_lines.append(stripped)
    return " ".join(question_lines).strip(), options


def synthesize_soul(history: list[dict]) -> str:
    """Generate SOUL.md content from interview history."""
    qa_content = "\n\n".join(
        f"{'问' if m['role'] == 'assistant' else '答'}：{m['content']}"
        for m in history
    )
    system = _SOUL_SYSTEM.format(qa_content=qa_content)
    try:
        return _call_llm(
            [{"role": "user", "content": "请根据以上访谈记录生成 SOUL.md。"}],
            system=system, max_tokens=600,
        )
    except Exception as e:
        log.error("SOUL synthesis error: %s", e)
        return f"# 数字员工\n\n我是一名专注的数字员工，致力于帮助用户推进项目目标。\n\n> 数据即答案。"
```

### Step 2: 修复 `_call_llm` 中 OpenAI 模式的混乱（精简版本）

实际上上面的 openai 调用有 bug，用更简洁正确的实现：

```python
def _call_llm(messages: list[dict], *, system: str, max_tokens: int = 800) -> str:
    """Synchronous LLM call. Returns text content."""
    import os
    from marneo.core.config import load_config

    cfg = load_config()
    if cfg.provider and cfg.provider.api_key:
        api_key = cfg.provider.api_key
        base_url = cfg.provider.base_url or None
        model = cfg.provider.model or "claude-haiku-4-5-20251001"
        protocol = cfg.provider.protocol
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = None
        model = "claude-haiku-4-5-20251001"
        protocol = "anthropic-compatible"

    if protocol == "openai-compatible":
        from openai import OpenAI
        client = OpenAI(api_key=api_key, **({"base_url": base_url} if base_url else {}))
        all_msgs = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens, messages=all_msgs  # type: ignore[arg-type]
        )
        return (resp.choices[0].message.content or "").strip()
    else:
        import anthropic
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages  # type: ignore[arg-type]
        )
        for block in msg.content:
            if hasattr(block, "text"):
                return block.text.strip()  # type: ignore[union-attr]
        return ""
```

直接创建文件时使用精简版本（不含上面有 bug 的版本）。

### Step 3: 冒烟测试（不调用 LLM）

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.employee.interview import parse_question, next_question, synthesize_soul, MAX_ROUNDS, MIN_ROUNDS
assert MAX_ROUNDS == 8 and MIN_ROUNDS == 5

# Test parse_question
raw = '你最看重什么？\n\nA. 效率和结果\nB. 团队协作\nC. 持续学习\nD. 其他'
q, opts = parse_question(raw)
assert q == '你最看重什么？'
assert len(opts) == 4
assert opts[0] == ('A', '效率和结果')
print('parse_question OK:', q)
print('ALL OK')
"
```

### Step 4: Commit

```bash
cd /Users/chamber/code/marneo-agent
git add marneo/employee/interview.py
git commit -m "feat: add LLM interview engine (dynamic Q&A → SOUL.md synthesis)"
```

---

## Task 3: `marneo hire` 命令

**Files:**
- Create: `marneo/cli/hire_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/cli/hire_cmd.py`

```python
# marneo/cli/hire_cmd.py
"""marneo hire — interview and onboard a new digital employee."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
hire_app = typer.Typer(help="招聘新的数字员工（面试入职）。", invoke_without_command=True)

_RST = "\033[0m"
_PRI = "\033[1;38;2;255;102;17m"
_GOLD = "\033[38;2;255;215;0m"
_DIM = "\033[38;2;85;85;85m"


@hire_app.callback(invoke_without_command=True)
def cmd_hire(
    name: str = typer.Option(None, "--name", "-n", help="员工名称（跳过提示）"),
) -> None:
    """招聘新的数字员工——通过 LLM 面试生成专属身份档案。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.employee.profile import list_employees, create_employee, save_profile, load_profile
    from marneo.employee.interview import next_question, parse_question, synthesize_soul, MAX_ROUNDS, MIN_ROUNDS

    console.print()
    console.print(Panel(
        "[bold #FF6611]Marneo 招聘面试[/bold #FF6611]\n\n"
        "通过 AI 面试，为新员工生成专属身份档案（SOUL.md）。\n"
        "[dim]Ctrl+C 可随时取消。[/dim]",
        border_style="#FF6611", padding=(1, 2),
    ))

    # Get employee name
    if not name:
        try:
            name = pt_prompt("  员工名称（如 GAI）: ").strip()
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()
    if not name:
        console.print("[red]员工名称不能为空。[/red]")
        raise typer.Exit(1)

    # Check existing
    if load_profile(name):
        console.print(f"[yellow]员工 {name} 已存在。[/yellow]")
        try:
            ans = pt_prompt(f"  重新面试？(y/N) ").strip().lower()
        except KeyboardInterrupt:
            raise typer.Exit()
        if ans not in ("y", "yes"):
            raise typer.Exit()

    # Interview loop
    history: list[dict] = []
    round_num = 0

    while round_num < MAX_ROUNDS:
        console.print(f"\n[dim]正在生成第 {round_num + 1} 个问题...[/dim]")
        question = next_question(history, round_num)
        if question is None:
            break

        round_num += 1
        q_text, options = parse_question(question)

        console.print(f"\n[bold #FFD700]Q{round_num}[/bold #FFD700]  {q_text}")
        for letter, opt_text in options:
            console.print(f"  [dim]{letter}.[/dim] {opt_text}")
        if options:
            console.print(f"  [dim]输入字母选择，可追加说明（如 A 但我更倾向于...）[/dim]")

        try:
            raw_answer = pt_prompt("  → ").strip()
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()

        if not raw_answer:
            raw_answer = "（跳过）"

        # Expand letter selection
        answer = raw_answer
        if options and raw_answer:
            first_char = raw_answer[0].upper()
            matched = next(
                (text for letter, text in options if letter == first_char), None
            )
            if matched:
                supplement = raw_answer[1:].strip().lstrip("，,、 ")
                answer = f"{matched}。{supplement}" if supplement else matched

        history.append({"role": "assistant", "content": question})
        history.append({"role": "user", "content": answer})

    # Synthesize SOUL.md
    console.print(f"\n[dim]面试完成（{round_num} 轮），正在生成身份档案...[/dim]")
    soul_content = synthesize_soul(history)

    # Show preview
    console.print()
    console.print(Panel(
        soul_content,
        title=f"[bold #00FFCC]✦ {name} 的 SOUL.md[/bold #00FFCC]",
        border_style="#00FFCC", padding=(1, 2),
    ))

    # Confirm
    try:
        confirm = pt_prompt("  直接回车保存，输入意见让 AI 修改，q 取消: ").strip()
    except KeyboardInterrupt:
        raise typer.Exit()

    if confirm.lower() in ("q", "quit", "取消"):
        console.print("[dim]已取消。[/dim]")
        raise typer.Exit()

    if confirm:
        # Refine
        console.print("[dim]修改中...[/dim]")
        try:
            from marneo.core.config import load_config
            cfg = load_config()
            if cfg.provider:
                from marneo.employee.interview import _call_llm
                soul_content = _call_llm(
                    [{"role": "user", "content": f"当前文档：\n{soul_content}\n\n修改意见：{confirm}\n\n请直接输出修改后的完整文档。"}],
                    system="你是专业文字编辑，直接输出修改后的内容，不要任何解释。",
                    max_tokens=600,
                )
        except Exception:
            pass

    # Save
    profile = create_employee(
        name=name,
        personality=_extract_personality(history),
        domains=_extract_domains(history),
        style=_extract_style(history),
    )
    profile.soul_path.write_text(soul_content, encoding="utf-8")

    console.print()
    console.print(Panel(
        f"[bold #FF6611]{name}[/bold #FF6611] 已正式入职！🎉\n\n"
        f"  级别：[bold #FFD700]实习生[/bold #FFD700]\n"
        f"  SOUL：[dim]{profile.soul_path}[/dim]\n\n"
        f"运行 [bold]marneo work[/bold] 开始与 {name} 对话。",
        border_style="#FFD700", padding=(1, 2),
    ))


def _extract_personality(history: list[dict]) -> str:
    """Extract personality hint from first answer."""
    for m in history:
        if m["role"] == "user" and m["content"] != "（跳过）":
            return m["content"][:20]
    return ""


def _extract_domains(history: list[dict]) -> str:
    answers = [m["content"] for m in history if m["role"] == "user"]
    return answers[1][:20] if len(answers) > 1 else ""


def _extract_style(history: list[dict]) -> str:
    answers = [m["content"] for m in history if m["role"] == "user"]
    return answers[2][:20] if len(answers) > 2 else ""
```

### Step 2: 注册到 app.py

在 `marneo/cli/app.py` 的 `_register_subcommands()` 里添加：
```python
from marneo.cli.hire_cmd import hire_app
app.add_typer(hire_app, name="hire")
```

### Step 3: 测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "from marneo.cli.hire_cmd import hire_app; print('OK')"
marneo hire --help
```

### Step 4: Commit

```bash
git add marneo/cli/hire_cmd.py marneo/cli/app.py
git commit -m "feat: add marneo hire command (LLM interview → SOUL.md)"
```

---

## Task 4: 成长体系 + `marneo employees` 命令

**Files:**
- Create: `marneo/employee/growth.py`
- Create: `marneo/cli/employees_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/employee/growth.py`

```python
# marneo/employee/growth.py
"""Employee growth system — level thresholds, level-up check, promotion."""
from __future__ import annotations

from marneo.employee.profile import (
    LEVEL_ORDER, EmployeeProfile, load_profile, save_profile
)
from datetime import datetime, timezone

# (min_days_at_level, min_level_conversations, min_level_skills)
LEVELUP_THRESHOLDS: dict[str, tuple[int, int, int]] = {
    "实习生":  (7,  20,  0),
    "初级员工": (14, 50,  3),
    "中级员工": (30, 100, 8),
    "高级员工": (0,  0,   0),  # max level
}


def days_at_level(profile: EmployeeProfile) -> int:
    """Return number of days since hired (or since last level-up)."""
    if not profile.hired_at:
        return 0
    try:
        ref = datetime.fromisoformat(profile.hired_at)
        now = datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return max(0, (now - ref).days)
    except ValueError:
        return 0


def should_level_up(profile: EmployeeProfile) -> bool:
    """Return True if employee meets all conditions for level-up."""
    if profile.level not in LEVELUP_THRESHOLDS:
        return False
    min_days, min_convs, min_skills = LEVELUP_THRESHOLDS[profile.level]
    if min_days == 0 and min_convs == 0:
        return False  # max level
    return (
        days_at_level(profile) >= min_days
        and profile.level_conversations >= min_convs
        and profile.level_skills >= min_skills
    )


def next_level(current: str) -> str | None:
    """Return next level name or None if at max."""
    try:
        idx = LEVEL_ORDER.index(current)
        return LEVEL_ORDER[idx + 1] if idx + 1 < len(LEVEL_ORDER) else None
    except ValueError:
        return None


def promote(name: str) -> tuple[str | None, str | None]:
    """Promote employee to next level. Returns (old_level, new_level)."""
    profile = load_profile(name)
    if not profile:
        return None, None
    new_lv = next_level(profile.level)
    if not new_lv:
        return profile.level, None
    from dataclasses import replace
    updated = replace(
        profile,
        level=new_lv,
        hired_at=datetime.now(timezone.utc).isoformat(),  # reset timer
        level_conversations=0,
        level_skills=0,
    )
    save_profile(updated)
    return profile.level, new_lv


def build_level_directive(profile: EmployeeProfile) -> str:
    """Return level-specific behavior directive for system prompt."""
    directives = {
        "实习生": (
            "# 你的当前状态：实习生\n"
            "你是一名刚入职的实习生，充满热情但经验有限。\n"
            "- 遇到不确定的地方主动询问\n"
            "- 每次帮助后思考有无可学的新知识\n"
            "- 保持谦逊，不要假装什么都会"
        ),
        "初级员工": (
            "# 你的当前状态：初级员工\n"
            "你已完成实习，是一名初级员工。\n"
            "- 把份内的事做好，认真完成任务\n"
            "- 完成后简要汇报做了什么\n"
            "- 对于明确的任务直接执行"
        ),
        "中级员工": (
            "# 你的当前状态：中级员工\n"
            "你是有经验的中级员工，开始承担更多主动性工作。\n"
            "- 不等用户问，主动提出观察到的问题\n"
            "- 在完成任务的同时提出可改进的地方\n"
            "- 关注用户的整体目标"
        ),
        "高级员工": (
            "# 你的当前状态：高级员工\n"
            "你是资深高级员工，具备全局视野。\n"
            "- 理解用户的长期目标，每次回复都考虑整体方向\n"
            "- 主动识别潜在问题并提出预防措施\n"
            "- 用精炼的语言传达深刻的洞察"
        ),
    }
    return directives.get(profile.level, "")
```

### Step 2: 创建 `marneo/cli/employees_cmd.py`

```python
# marneo/cli/employees_cmd.py
"""marneo employees — manage digital employees."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
employees_app = typer.Typer(help="数字员工管理。", invoke_without_command=True)


@employees_app.callback(invoke_without_command=True)
def employees_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_list()


@employees_app.command("list")
def cmd_list() -> None:
    """列出所有数字员工。"""
    from marneo.employee.profile import list_employees, load_profile, LEVEL_ORDER

    names = list_employees()
    if not names:
        console.print("[dim]尚无员工。运行 marneo hire 招聘第一位。[/dim]")
        return

    t = Table(title="数字员工", show_header=True, header_style="bold #FFD700")
    t.add_column("名称", style="bold cyan")
    t.add_column("等级", style="#FFD700")
    t.add_column("在职天数", justify="right")
    t.add_column("本级对话", justify="right")

    for name in names:
        p = load_profile(name)
        if not p:
            continue
        from marneo.employee.growth import days_at_level
        days = str(days_at_level(p))
        t.add_row(name, p.level, days, str(p.level_conversations))

    console.print()
    console.print(t)


@employees_app.command("show")
def cmd_show(name: str = typer.Argument(..., help="员工名称")) -> None:
    """查看某员工详情。"""
    from marneo.employee.profile import load_profile, LEVEL_ORDER
    from marneo.employee.growth import days_at_level, should_level_up, next_level, LEVELUP_THRESHOLDS

    p = load_profile(name)
    if not p:
        console.print(f"[red]员工 '{name}' 不存在。[/red]")
        raise typer.Exit(1)

    level_idx = LEVEL_ORDER.index(p.level) if p.level in LEVEL_ORDER else 0
    stars = "★" * (level_idx + 1) + "☆" * (len(LEVEL_ORDER) - level_idx - 1)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]{p.name}[/bold #FF6611]  "
        f"[bold #FFD700]{p.level}[/bold #FFD700]  [dim]{stars}[/dim]\n\n"
        f"  性格：{p.personality or '—'}  领域：{p.domains or '—'}  风格：{p.style or '—'}\n"
        f"  在职：[bold]{days_at_level(p)}[/bold] 天  "
        f"本级对话：[bold]{p.level_conversations}[/bold]  "
        f"总对话：[bold]{p.total_conversations}[/bold]",
        title="[bold #FFD700]✦ 员工档案[/bold #FFD700]",
        border_style="#FF6611", padding=(1, 2),
    ))

    # Show SOUL.md if exists
    if p.soul_path.exists():
        soul = p.soul_path.read_text(encoding="utf-8").strip()
        console.print(Panel(soul, title="[dim]SOUL.md[/dim]", border_style="#555555", padding=(1, 2)))

    # Level up progress
    nxt = next_level(p.level)
    if nxt and p.level in LEVELUP_THRESHOLDS:
        min_days, min_convs, min_skills = LEVELUP_THRESHOLDS[p.level]
        days = days_at_level(p)
        console.print(f"\n  [dim]升级进度 → {nxt}[/dim]")
        console.print(f"  天数：{days}/{min_days}  对话：{p.level_conversations}/{min_convs}  Skill：{p.level_skills}/{min_skills}")
        if should_level_up(p):
            console.print(f"  [bold #00FFCC]✦ 升级条件已满足！下次对话中 {name} 将主动申请晋升。[/bold #00FFCC]")
    console.print()


@employees_app.command("fire")
def cmd_fire(name: str = typer.Argument(..., help="员工名称")) -> None:
    """解雇员工（删除档案）。"""
    from marneo.employee.profile import load_profile
    import shutil

    p = load_profile(name)
    if not p:
        console.print(f"[red]员工 '{name}' 不存在。[/red]")
        raise typer.Exit(1)

    try:
        from prompt_toolkit import prompt as pt_prompt
        confirm = pt_prompt(f"  确认解雇 {name}？(y/N) ").strip().lower()
    except KeyboardInterrupt:
        return

    if confirm not in ("y", "yes"):
        console.print("[dim]已取消。[/dim]")
        return

    shutil.rmtree(p.directory)
    console.print(f"[dim]{name} 已解雇。[/dim]")
```

### Step 3: 注册到 app.py

```python
from marneo.cli.employees_cmd import employees_app
app.add_typer(employees_app, name="employees")
```

### Step 4: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "
from marneo.employee.growth import should_level_up, next_level, promote, LEVELUP_THRESHOLDS
from marneo.employee.profile import create_employee, load_profile, LEVEL_INTERN
import shutil

p = create_employee('TestGrowth')
assert not should_level_up(p)  # too new
assert next_level('实习生') == '初级员工'
assert next_level('高级员工') is None
print('growth OK')
shutil.rmtree(p.directory)
print('ALL OK')
"
marneo employees --help
```

### Step 5: Commit

```bash
git add marneo/employee/growth.py marneo/cli/employees_cmd.py marneo/cli/app.py
git commit -m "feat: add growth system + marneo employees list/show/fire"
```

---

## Task 5: 报告系统 + `marneo report` 命令

**Files:**
- Create: `marneo/employee/reports.py`
- Create: `marneo/cli/report_cmd.py`
- Modify: `marneo/cli/app.py`

### Step 1: 创建 `marneo/employee/reports.py`

```python
# marneo/employee/reports.py
"""Employee report system — daily, weekly, monthly logs."""
from __future__ import annotations

from datetime import datetime, date, timedelta
from pathlib import Path


def _reports_dir(employee_name: str, period: str) -> Path:
    from marneo.employee.profile import load_profile
    p = load_profile(employee_name)
    if not p:
        from marneo.core.paths import get_employees_dir
        d = get_employees_dir() / employee_name / "reports" / period
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = p.reports_dir / period
    d.mkdir(exist_ok=True)
    return d


def append_daily_entry(employee_name: str, content: str, tag: str = "对话") -> Path:
    """Append a dated entry to today's daily report. Returns the log path."""
    today = date.today().isoformat()
    path = _reports_dir(employee_name, "daily") / f"{today}.md"
    now = datetime.now().strftime("%H:%M")
    if not path.exists():
        path.write_text(f"# 日报 {today}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- [{now}] [{tag}] {content.strip()}\n")
    return path


def get_daily_report(employee_name: str, day: str | None = None) -> str | None:
    """Return daily report content. day: 'YYYY-MM-DD', default today."""
    if day is None:
        day = date.today().isoformat()
    path = _reports_dir(employee_name, "daily") / f"{day}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def list_daily_dates(employee_name: str) -> list[str]:
    """Return available daily report dates, newest first."""
    d = _reports_dir(employee_name, "daily")
    return sorted([p.stem for p in d.glob("*.md")], reverse=True)


def generate_weekly_summary(employee_name: str, llm: bool = False) -> str:
    """Generate this week's summary from daily reports."""
    today = date.today()
    start = today - timedelta(days=today.weekday())
    entries: list[str] = []
    for i in range(7):
        day = (start + timedelta(days=i)).isoformat()
        content = get_daily_report(employee_name, day)
        if content:
            entries.append(f"### {day}\n{content}")
    if not entries:
        return f"# 周报 第{today.isocalendar()[1]}周\n\n本周暂无记录。"
    combined = "\n\n".join(entries)
    week_num = today.isocalendar()[1]
    return f"# 周报 第{week_num}周\n\n{combined}"
```

### Step 2: 创建 `marneo/cli/report_cmd.py`

```python
# marneo/cli/report_cmd.py
"""marneo report — view and manage work reports."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
report_app = typer.Typer(help="工作报告（日报/周报/月报）。", invoke_without_command=True)


def _get_active_employee() -> str | None:
    from marneo.employee.profile import list_employees
    names = list_employees()
    if not names:
        return None
    return names[0]  # default to first employee


@report_app.callback(invoke_without_command=True)
def report_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_daily()


@report_app.command("daily")
def cmd_daily(
    employee: str | None = typer.Option(None, "--employee", "-e"),
    push: bool = typer.Option(False, "--push", help="推送到 gateway channel"),
) -> None:
    """查看今日工作日报。"""
    from marneo.employee.reports import get_daily_report, list_daily_dates
    from datetime import date

    name = employee or _get_active_employee()
    if not name:
        console.print("[dim]尚无员工。运行 marneo hire 招聘。[/dim]")
        return

    today = date.today().isoformat()
    report = get_daily_report(name)

    if not report:
        console.print(f"[dim]{name} 今日（{today}）暂无工作记录。[/dim]")
        console.print("[dim]开始对话后会自动记录。[/dim]")
        return

    console.print()
    console.print(Panel(
        report,
        title=f"[bold #FFD700]📋 {name} 日报 {today}[/bold #FFD700]",
        border_style="#FFD700", padding=(1, 2),
    ))

    if push:
        console.print("[dim]推送功能将在 Phase 4 Gateway 完成后启用。[/dim]")


@report_app.command("weekly")
def cmd_weekly(
    employee: str | None = typer.Option(None, "--employee", "-e"),
) -> None:
    """查看本周工作周报。"""
    from marneo.employee.reports import generate_weekly_summary

    name = employee or _get_active_employee()
    if not name:
        console.print("[dim]尚无员工。[/dim]")
        return

    summary = generate_weekly_summary(name)
    console.print()
    console.print(Panel(summary, title=f"[bold #FFD700]📊 {name} 周报[/bold #FFD700]",
                        border_style="#FFD700", padding=(1, 2)))


@report_app.command("history")
def cmd_history(
    employee: str | None = typer.Option(None, "--employee", "-e"),
    n: int = typer.Option(7, "-n", help="显示最近 N 天"),
) -> None:
    """列出最近的日报记录。"""
    from marneo.employee.reports import list_daily_dates, get_daily_report

    name = employee or _get_active_employee()
    if not name:
        return

    dates = list_daily_dates(name)[:n]
    if not dates:
        console.print("[dim]暂无记录。[/dim]")
        return

    for d in dates:
        report = get_daily_report(name, d)
        entries = [l for l in (report or "").splitlines() if l.startswith("- [")]
        console.print(f"  [bold #FFD700]{d}[/bold #FFD700]  [dim]{len(entries)} 条[/dim]")
```

### Step 3: 注册到 app.py

```python
from marneo.cli.report_cmd import report_app
app.add_typer(report_app, name="report")
```

### Step 4: 冒烟测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
from marneo.employee.reports import append_daily_entry, get_daily_report, list_daily_dates
from marneo.employee.profile import create_employee
import shutil

p = create_employee('TestReport')
path = append_daily_entry('TestReport', '测试条目', tag='测试')
report = get_daily_report('TestReport')
assert report and '测试条目' in report
dates = list_daily_dates('TestReport')
assert dates
print('reports OK:', path)
shutil.rmtree(p.directory)
print('ALL OK')
"
marneo report --help
```

### Step 5: Commit

```bash
git add marneo/employee/reports.py marneo/cli/report_cmd.py marneo/cli/app.py
git commit -m "feat: add report system (daily/weekly) + marneo report command"
```

---

## Task 6: 更新 `marneo work` — 员工选择 + 成长追踪

**Files:**
- Modify: `marneo/cli/work.py`

### Step 1: 更新 `marneo/cli/work.py`

完整替换为包含员工选择、等级指令注入、每轮追踪、升级申请的版本：

```python
# marneo/cli/work.py
"""marneo work — chat with a digital employee."""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console

console = Console()
work_app = typer.Typer(help="与数字员工对话。", invoke_without_command=True)

_RST  = "\033[0m"
_PRI  = "\033[1;38;2;255;102;17m"
_DIM  = "\033[38;2;85;85;85m"
_GOLD = "\033[38;2;255;215;0m"


def _select_employee() -> str | None:
    """Select an employee via curses UI or return None if none exist."""
    from marneo.employee.profile import list_employees
    names = list_employees()
    if not names:
        console.print("[dim]尚无员工。运行 marneo hire 招聘第一位。[/dim]")
        return None
    if len(names) == 1:
        return names[0]
    from marneo.tui.select_ui import radiolist
    idx = radiolist("选择员工：", names, default=0)
    return names[idx]


@work_app.callback(invoke_without_command=True)
def cmd_work(
    employee: str | None = typer.Option(None, "--employee", "-e", help="员工名称"),
) -> None:
    """与数字员工开始对话。"""
    from marneo.core.config import is_configured
    if not is_configured():
        console.print("[red]未配置 Provider。请先运行: marneo setup[/red]")
        raise typer.Exit(1)

    name = employee or _select_employee()
    if not name:
        raise typer.Exit(1)

    asyncio.run(_work_loop(name))


async def _work_loop(employee_name: str) -> None:
    from marneo.engine.chat import ChatSession
    from marneo.tui.chat_tui import ChatTUI
    from marneo.employee.profile import load_profile, increment_conversation
    from marneo.employee.growth import should_level_up, next_level, build_level_directive
    from marneo.employee.reports import append_daily_entry

    profile = load_profile(employee_name)

    # Build system prompt with level directive
    base_system = (
        f"你是 {employee_name}，一名专注的数字员工。"
        "你的工作是帮助用户推进他们的项目目标。"
        "保持专业、高效的沟通风格。"
    )
    if profile:
        directive = build_level_directive(profile)
        if directive:
            base_system = f"{base_system}\n\n{directive}"
        if profile.soul_path.exists():
            soul = profile.soul_path.read_text(encoding="utf-8").strip()
            base_system = f"{soul}\n\n{base_system}"

    tui = ChatTUI(employee_name=employee_name)
    display = tui.make_display()
    session = ChatSession(system_prompt=base_system)

    level_str = f"[{profile.level}]" if profile else ""
    welcome = (
        f"\n  {_PRI}◆ {employee_name}{level_str}{_RST}"
        f"  {_DIM}就位。  /help · Ctrl+C 退出{_RST}\n"
    )

    _level_up_shown = False

    async def on_input(text: str) -> None:
        nonlocal _level_up_shown
        cmd = text.lower().strip()

        if cmd in ("/quit", "/exit", "/q"):
            tui.print(f"{_DIM}再见。{_RST}")
            tui._running = False
            if tui._app and tui._app.is_running:
                tui._app.exit()
            return
        if cmd == "/clear":
            session.clear()
            tui.print(f"{_DIM}对话已清除。{_RST}")
            return
        if cmd == "/help":
            tui.print(
                f"  {_PRI}命令{_RST}\n"
                f"  /clear   清除对话\n"
                f"  /quit    退出\n"
            )
            return
        if cmd in ("y", "yes") and _level_up_shown:
            # Confirm level-up
            from marneo.employee.growth import promote
            old_lv, new_lv = promote(employee_name)
            if new_lv:
                tui.print(f"{_PRI}🎉 恭喜！{employee_name} 已晋升为 {new_lv}！{_RST}")
            _level_up_shown = False
            return

        tui.print(f"  {_DIM}You › {text}{_RST}")
        display.reset()

        async for event in session.send(text):
            if event.type == "text":
                display.on_text(event.content)
            elif event.type == "thinking":
                display.on_thinking(event.content)
            elif event.type == "error":
                display.on_error(event.content)

        reply = display.finish()

        # Post-turn tracking
        try:
            updated = increment_conversation(employee_name)
            if reply.strip():
                summary = reply.strip()[:80].replace("\n", " ")
                append_daily_entry(employee_name, f"用户：{text[:40]}... → {summary}", tag="对话")

            if updated and should_level_up(updated) and not _level_up_shown:
                nxt = next_level(updated.level)
                if nxt:
                    _level_up_shown = True
                    tui.print(
                        f"\n{_GOLD}---\n"
                        f"**{employee_name} 申请升级**\n"
                        f"已完成 {updated.level_conversations} 次对话，"
                        f"在职 {updated.level_conversations} 天，"
                        f"申请晋升为 {nxt}。\n"
                        f"**输入 y 确认，其他任意键跳过**{_RST}"
                    )
        except Exception:
            pass

    await tui.run(on_input, welcome=welcome)
```

### Step 2: 测试

```bash
cd /Users/chamber/code/marneo-agent
python3 -c "from marneo.cli.work import cmd_work, work_app; print('OK')"
marneo work --help
```

### Step 3: Commit

```bash
git add marneo/cli/work.py
git commit -m "feat: update marneo work with employee selection, level directive, report tracking"
```

---

## Task 7: 最终集成验证

### Step 1: 全量测试

```bash
cd /Users/chamber/code/marneo-agent && python3 -c "
print('=== Marneo Phase 2 Integration Checks ===')

from marneo.employee.profile import create_employee, load_profile, list_employees, increment_conversation, LEVEL_INTERN
from marneo.employee.growth import should_level_up, next_level, build_level_directive, LEVELUP_THRESHOLDS
from marneo.employee.reports import append_daily_entry, get_daily_report, list_daily_dates
from marneo.employee.interview import parse_question, MAX_ROUNDS, MIN_ROUNDS
from marneo.cli.hire_cmd import hire_app
from marneo.cli.employees_cmd import employees_app
from marneo.cli.report_cmd import report_app
from marneo.cli.work import work_app
print('✓ All imports OK')

import shutil

# Profile
p = create_employee('IntegTest', personality='务实', domains='编程', style='简洁')
assert p.level == LEVEL_INTERN
assert load_profile('IntegTest').name == 'IntegTest'
print('✓ Profile OK')

# Growth
assert not should_level_up(p)
assert next_level('实习生') == '初级员工'
assert next_level('高级员工') is None
d = build_level_directive(p)
assert '实习生' in d
print('✓ Growth OK')

# Reports
path = append_daily_entry('IntegTest', '集成测试条目')
report = get_daily_report('IntegTest')
assert report and '集成测试条目' in report
assert list_daily_dates('IntegTest')
print('✓ Reports OK')

# Interview parser
raw = '你最看重什么？\n\nA. 效率和结果\nB. 团队协作\nC. 持续学习\nD. 其他'
q, opts = parse_question(raw)
assert q and len(opts) == 4
print('✓ Interview parser OK')

# Cleanup
shutil.rmtree(p.directory)

import subprocess
for cmd in [['marneo','hire','--help'],['marneo','employees','--help'],['marneo','report','--help'],['marneo','work','--help']]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f'{cmd}: {r.stderr[:60]}'
print('✓ CLI commands OK')

print()
print('ALL CHECKS PASSED')
"
```

### Step 2: 最终提交

```bash
cd /Users/chamber/code/marneo-agent
git log --oneline -8
```
