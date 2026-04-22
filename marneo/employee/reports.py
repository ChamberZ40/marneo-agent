# marneo/employee/reports.py
"""Employee report system — daily, weekly logs."""
from __future__ import annotations

from datetime import datetime, date, timedelta
from pathlib import Path


def _reports_dir(employee_name: str, period: str) -> Path:
    from marneo.core.paths import get_employees_dir
    d = get_employees_dir() / employee_name / "reports" / period
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_daily_entry(employee_name: str, content: str, tag: str = "对话") -> Path:
    """Append entry to today's daily report. Returns log path."""
    today = date.today().isoformat()
    path = _reports_dir(employee_name, "daily") / f"{today}.md"
    now = datetime.now().strftime("%H:%M")
    if not path.exists():
        path.write_text(f"# 日报 {today}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- [{now}] [{tag}] {content.strip()}\n")
    return path


def get_daily_report(employee_name: str, day: str | None = None) -> str | None:
    """Return daily report content for given day (default today)."""
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


def generate_weekly_summary(employee_name: str) -> str:
    """Generate this week's summary from daily reports."""
    today = date.today()
    start = today - timedelta(days=today.weekday())
    entries: list[str] = []
    for i in range(7):
        day = (start + timedelta(days=i)).isoformat()
        content = get_daily_report(employee_name, day)
        if content:
            entries.append(f"### {day}\n{content}")
    week_num = today.isocalendar()[1]
    if not entries:
        return f"# 周报 第{week_num}周\n\n本周暂无记录。"
    return f"# 周报 第{week_num}周\n\n" + "\n\n".join(entries)
