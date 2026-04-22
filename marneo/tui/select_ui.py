"""Terminal selection UI components — ported from Hermes hermes_cli/curses_ui.py.

Provides curses-based arrow-key navigation with numbered-input fallback.
"""
from __future__ import annotations

import sys
from typing import Callable, Optional, Set


def _flush_stdin() -> None:
    """Flush stray bytes from stdin after curses exits."""
    try:
        if not sys.stdin.isatty():
            return
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def radiolist(
    title: str,
    items: list[str],
    default: int = 0,
) -> int:
    """Single-select with arrow keys. Returns selected index.

    ↑↓ navigate  Enter/Space select  ESC/q cancel (returns default)
    """
    if not sys.stdin.isatty():
        return default

    try:
        import curses
        result: list[int] = [default]

        def _draw(stdscr: object) -> None:
            import curses as _c
            _c.curs_set(0)
            if _c.has_colors():
                _c.start_color()
                _c.use_default_colors()
                _c.init_pair(1, _c.COLOR_GREEN, -1)
                _c.init_pair(2, _c.COLOR_YELLOW, -1)
            cursor = default
            scroll = 0

            while True:
                stdscr.clear()  # type: ignore[attr-defined]
                max_y, max_x = stdscr.getmaxyx()  # type: ignore[attr-defined]

                try:
                    hattr = _c.A_BOLD | (_c.color_pair(2) if _c.has_colors() else 0)
                    stdscr.addnstr(0, 0, title, max_x - 1, hattr)  # type: ignore[attr-defined]
                    stdscr.addnstr(1, 0, "  ↑↓移动  Enter确认  ESC取消", max_x - 1, _c.A_DIM)  # type: ignore[attr-defined]
                except _c.error:
                    pass

                visible = max_y - 4
                if cursor < scroll:
                    scroll = cursor
                elif cursor >= scroll + visible:
                    scroll = cursor - visible + 1

                for di, i in enumerate(range(scroll, min(len(items), scroll + visible))):
                    y = di + 3
                    if y >= max_y - 1:
                        break
                    radio = "◉" if i == cursor else "○"
                    line = f"  {radio}  {items[i]}"
                    attr = _c.A_BOLD | (_c.color_pair(1) if _c.has_colors() else 0) if i == cursor else _c.A_NORMAL
                    try:
                        stdscr.addnstr(y, 0, line, max_x - 1, attr)  # type: ignore[attr-defined]
                    except _c.error:
                        pass

                stdscr.refresh()  # type: ignore[attr-defined]
                key = stdscr.getch()  # type: ignore[attr-defined]
                if key in (_c.KEY_UP, ord("k")):
                    cursor = (cursor - 1) % len(items)
                elif key in (_c.KEY_DOWN, ord("j")):
                    cursor = (cursor + 1) % len(items)
                elif key in (ord(" "), _c.KEY_ENTER, 10, 13):
                    result[0] = cursor
                    return
                elif key in (27, ord("q")):
                    result[0] = default
                    return

        curses.wrapper(_draw)
        _flush_stdin()
        return result[0]

    except Exception:
        return _radio_fallback(title, items, default)


def checklist(
    title: str,
    items: list[str],
    pre_selected: list[int] | None = None,
) -> list[int]:
    """Multi-select checklist with arrow keys. Returns list of selected indices.

    ↑↓ navigate  Space toggle  Enter confirm  ESC cancel
    """
    selected: set[int] = set(pre_selected or [])

    if not sys.stdin.isatty():
        return sorted(selected)

    try:
        import curses
        result: list[set[int]] = [set(selected)]

        def _draw(stdscr: object) -> None:
            import curses as _c
            _c.curs_set(0)
            if _c.has_colors():
                _c.start_color()
                _c.use_default_colors()
                _c.init_pair(1, _c.COLOR_GREEN, -1)
                _c.init_pair(2, _c.COLOR_YELLOW, -1)
            cursor = 0
            chosen = set(selected)
            scroll = 0

            while True:
                stdscr.clear()  # type: ignore[attr-defined]
                max_y, max_x = stdscr.getmaxyx()  # type: ignore[attr-defined]

                try:
                    hattr = _c.A_BOLD | (_c.color_pair(2) if _c.has_colors() else 0)
                    stdscr.addnstr(0, 0, title, max_x - 1, hattr)  # type: ignore[attr-defined]
                    stdscr.addnstr(1, 0, "  ↑↓移动  空格选择  Enter确认  ESC取消", max_x - 1, _c.A_DIM)  # type: ignore[attr-defined]
                except _c.error:
                    pass

                visible = max_y - 4
                if cursor < scroll:
                    scroll = cursor
                elif cursor >= scroll + visible:
                    scroll = cursor - visible + 1

                for di, i in enumerate(range(scroll, min(len(items), scroll + visible))):
                    y = di + 3
                    if y >= max_y - 1:
                        break
                    check = "✓" if i in chosen else " "
                    arrow = "→" if i == cursor else " "
                    line = f" {arrow} [{check}] {items[i]}"
                    attr = _c.A_BOLD | (_c.color_pair(1) if _c.has_colors() else 0) if i == cursor else _c.A_NORMAL
                    try:
                        stdscr.addnstr(y, 0, line, max_x - 1, attr)  # type: ignore[attr-defined]
                    except _c.error:
                        pass

                stdscr.refresh()  # type: ignore[attr-defined]
                key = stdscr.getch()  # type: ignore[attr-defined]
                if key in (_c.KEY_UP, ord("k")):
                    cursor = (cursor - 1) % len(items)
                elif key in (_c.KEY_DOWN, ord("j")):
                    cursor = (cursor + 1) % len(items)
                elif key == ord(" "):
                    chosen.symmetric_difference_update({cursor})
                elif key in (_c.KEY_ENTER, 10, 13):
                    result[0] = set(chosen)
                    return
                elif key in (27, ord("q")):
                    result[0] = set(selected)  # restore original on ESC
                    return

        curses.wrapper(_draw)
        _flush_stdin()
        return sorted(result[0])

    except Exception:
        return _checklist_fallback(title, items, sorted(selected))


# ---------------------------------------------------------------------------
# Numbered fallbacks (non-TTY / curses unavailable)
# ---------------------------------------------------------------------------

def _radio_fallback(title: str, items: list[str], default: int) -> int:
    print(f"\n  {title}")
    for i, label in enumerate(items):
        marker = "◉" if i == default else "○"
        print(f"  {marker} {i + 1}. {label}")
    try:
        val = input(f"\n  选择 [默认 {default + 1}]: ").strip()
        if not val:
            return default
        idx = int(val) - 1
        return idx if 0 <= idx < len(items) else default
    except (ValueError, KeyboardInterrupt, EOFError):
        return default


def _checklist_fallback(title: str, items: list[str], pre_selected: list[int]) -> list[int]:
    print(f"\n  {title}")
    selected = set(pre_selected)
    for i, label in enumerate(items):
        mark = "✓" if i in selected else " "
        print(f"  [{mark}] {i + 1}. {label}")
    print(f"\n  当前已选: {[i+1 for i in sorted(selected)] or '无'}")
    try:
        val = input("  输入序号切换选择（多个用逗号，回车确认）: ").strip()
        if val:
            for part in val.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(items):
                        if idx in selected:
                            selected.discard(idx)
                        else:
                            selected.add(idx)
        return sorted(selected)
    except (KeyboardInterrupt, EOFError):
        return pre_selected
