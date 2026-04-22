# marneo/tui/chat_tui.py
"""Marneo chat TUI — fixed bottom input + streaming Markdown output."""
from __future__ import annotations

import asyncio
import queue
import shutil
import time
from typing import Any, Awaitable, Callable

from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import TextArea

from marneo.core.paths import get_marneo_dir

_RST  = "\033[0m"
_PRI  = "\033[1;38;2;255;102;17m"
_DIM  = "\033[38;2;85;85;85m"
_TEXT = "\033[38;2;224;224;224m"
_GOLD = "\033[38;2;255;215;0m"
_ERR  = "\033[38;2;255;51;51m"
_SPIN = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]


def _term_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns


class ChatTUI:
    """Marneo chat TUI with fixed bottom input and streaming Markdown output."""

    def __init__(self, employee_name: str = "Marneo") -> None:
        self._employee_name = employee_name
        self._input_queue: queue.Queue[str | None] = queue.Queue()
        self._app: Application | None = None
        self._running = False
        self._processing = False
        self._spin_idx = 0
        self._history_file = get_marneo_dir() / "chat_history"

    def print(self, text: str) -> None:
        _pt_print(_PT_ANSI(text + "\n"))

    def _build_app(self) -> Application:
        kb = KeyBindings()
        last_ctrl_c: list[float] = [0.0]

        @kb.add("enter")
        def _submit(event):  # type: ignore[misc]
            text = event.app.current_buffer.text.strip()
            if text:
                event.app.current_buffer.reset(append_to_history=True)
                self._input_queue.put(text)

        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _newline(event):  # type: ignore[misc]
            event.app.current_buffer.insert_text("\n")

        @kb.add("c-c")
        def _ctrlc(event):  # type: ignore[misc]
            buf = event.app.current_buffer
            if buf.text:
                buf.reset()
            else:
                now = time.monotonic()
                if now - last_ctrl_c[0] < 2.0:
                    self._input_queue.put(None)
                else:
                    last_ctrl_c[0] = now
                    self._input_queue.put("/__hint_exit__")

        @kb.add("c-d")
        def _eof(event):  # type: ignore[misc]
            self._input_queue.put(None)

        input_area = TextArea(
            height=Dimension(min=1, max=8, preferred=1),
            prompt=lambda: _PT_ANSI(f"{_PRI}❯ {_RST}"),
            multiline=True,
            wrap_lines=True,
            history=FileHistory(str(self._history_file)),
        )

        def _input_height() -> int:
            try:
                doc = input_area.buffer.document
                w = max(_term_width() - 4, 10)
                lines = sum(max(1, -(-len(ln) // w)) for ln in doc.lines)
                return min(max(lines, 1), 8)
            except Exception:
                return 1

        input_area.window.height = _input_height

        def _status_text() -> str:
            if self._processing:
                frame = _SPIN[self._spin_idx % len(_SPIN)]
                return f"{_PRI}{frame} 思考中...{_RST}"
            return (
                f"{_DIM}{self._employee_name}"
                f"  /help · Alt+Enter 换行 · Ctrl+C 退出{_RST}"
            )

        status_bar = Window(
            height=1,
            content=FormattedTextControl(lambda: _PT_ANSI(_status_text())),
        )

        layout = Layout(HSplit([
            Window(),
            Window(height=1, char="─", style="fg:#FF6611"),
            status_bar,
            input_area,
        ]))

        app = Application(
            layout=layout,
            key_bindings=kb,
            style=PTStyle.from_dict({"": "fg:#E0E0E0"}),
            mouse_support=False,
            full_screen=False,
        )
        self._app = app
        return app

    async def run(
        self,
        on_input: Callable[[str], Awaitable[None]],
        *,
        welcome: str = "",
    ) -> None:
        app = self._build_app()
        self._running = True
        loop = asyncio.get_event_loop()

        async def _app_task() -> None:
            with patch_stdout():
                if welcome:
                    self.print(welcome)
                await app.run_async()

        async def _spin_task() -> None:
            while self._running:
                await asyncio.sleep(0.1)
                if self._processing and app.is_running:
                    self._spin_idx += 1
                    app.invalidate()

        async def _process_loop() -> None:
            while self._running:
                try:
                    msg = await loop.run_in_executor(
                        None, lambda: self._input_queue.get(timeout=0.1)
                    )
                except Exception:
                    continue
                if msg is None:
                    self._running = False
                    if app.is_running:
                        app.exit()
                    break
                if msg == "/__hint_exit__":
                    self.print(f"{_DIM}再按 Ctrl+C 退出{_RST}")
                    continue
                self._processing = True
                if app.is_running:
                    app.invalidate()
                try:
                    await on_input(msg)
                finally:
                    self._processing = False
                    if app.is_running:
                        app.invalidate()

        await asyncio.gather(_app_task(), _spin_task(), _process_loop())

    # ── Stream Display ────────────────────────────────────────────────────

    class StreamDisplay:
        def __init__(self, tui: "ChatTUI") -> None:
            self._t = tui
            self._buf = ""
            self._thinking_buf = ""
            self._first_line = True
            self._accumulated = ""

        def reset(self) -> None:
            self._buf = ""
            self._thinking_buf = ""
            self._first_line = True
            self._accumulated = ""

        def on_thinking(self, text: str) -> None:
            self._thinking_buf += text  # hidden by default

        def on_text(self, text: str) -> None:
            self._accumulated += text
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._emit(line)

        def _emit(self, line: str) -> None:
            from marneo.tui.markdown_render import render_line
            rendered = render_line(line)
            if not line.strip():
                self._t.print("")
                return
            if self._first_line:
                self._t.print(f"  {_PRI}◆{_RST}  {rendered}")
                self._first_line = False
            else:
                self._t.print(f"     {rendered}")

        def on_error(self, content: str) -> None:
            self._t.print(f"  {_ERR}✗ {content}{_RST}")

        def finish(self) -> str:
            if self._buf.strip():
                self._emit(self._buf)
                self._buf = ""
            if not self._first_line:
                self._t.print("")
            return self._accumulated

    def make_display(self) -> "StreamDisplay":
        return self.StreamDisplay(self)
