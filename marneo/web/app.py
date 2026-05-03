"""Tiny zero-dependency HTTP server for the Marneo local web console."""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_bind_host(host: str, allow_lan: bool = False) -> str:
    """Validate that the web console is loopback-only unless LAN is explicit."""
    normalized = (host or "127.0.0.1").strip()
    if allow_lan or normalized in LOOPBACK_HOSTS:
        return normalized
    raise ValueError(
        "marneo web binds to 127.0.0.1 by default. Use --allow-lan to expose it beyond this machine."
    )


def render_index_html() -> str:
    """Return the built-in static UI."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Marneo Local Console</title>
  <style>
    :root { color-scheme: dark; --bg: #111; --panel: #1a1a1a; --text: #f5f1e8; --muted: #9b9388; --accent: #ff6611; --gold: #ffd700; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top left, #2b1608, var(--bg) 34rem); color: var(--text); }
    header { padding: 32px 28px 18px; border-bottom: 1px solid #2b2b2b; }
    h1 { margin: 0; color: var(--accent); letter-spacing: -0.03em; }
    .subtitle { color: var(--muted); margin-top: 8px; max-width: 850px; }
    main { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; padding: 24px 28px 40px; }
    section { background: color-mix(in srgb, var(--panel) 92%, transparent); border: 1px solid #292929; border-radius: 18px; padding: 18px; box-shadow: 0 18px 60px rgba(0,0,0,0.25); }
    h2 { margin: 0 0 12px; font-size: 18px; color: var(--gold); }
    pre, .item { background: #101010; border: 1px solid #262626; border-radius: 12px; padding: 12px; overflow: auto; }
    .item { margin: 8px 0; }
    .muted { color: var(--muted); }
    .ok { color: #73d13d; } .warn { color: #ffd666; }
    code { color: var(--gold); }
  </style>
</head>
<body>
  <header>
    <h1>Marneo Local Console</h1>
    <div class="subtitle">
      A loopback-only browser view over the same local employee/project data used by <code>marneo work</code>.
      Feishu remains the workplace gateway via <code>marneo gateway</code>; this page is only a local console.
    </div>
  </header>
  <main>
    <section><h2>Status</h2><div id="status" class="muted">Loading /api/status …</div></section>
    <section><h2>Employees</h2><div id="employees" class="muted">Loading /api/employees …</div></section>
    <section><h2>Projects</h2><div id="projects" class="muted">Loading /api/projects …</div></section>
  </main>
  <script>
    async function getJSON(path) {
      const res = await fetch(path);
      if (!res.ok) throw new Error(path + ' -> ' + res.status);
      return await res.json();
    }
    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    function renderStatus(data) {
      const provider = data.provider || {};
      document.querySelector('#status').innerHTML = `
        <div class="item"><b>Provider</b>: ${provider.configured ? '<span class="ok">configured</span>' : '<span class="warn">missing</span>'} ${esc(provider.id || '')} / ${esc(provider.model || '')}</div>
        <div class="item"><b>Privacy</b>: local_only=${esc(data.privacy?.local_only)}</div>
        <div class="item"><b>Gateway</b>: ${data.gateway?.running ? '<span class="ok">running</span>' : '<span class="muted">stopped</span>'}</div>
        <div class="item"><b>Default bind</b>: ${esc(data.server?.bind_default)}</div>`;
    }
    function renderEmployees(data) {
      const rows = (data.employees || []).map(e => `<div class="item"><b>${esc(e.name)}</b><br><span class="muted">${esc(e.level)} · ${esc((e.projects || []).join(', ') || 'no projects')}</span></div>`).join('');
      document.querySelector('#employees').innerHTML = rows || '<span class="muted">No employees yet. Run <code>marneo hire</code>.</span>';
    }
    function renderProjects(data) {
      const rows = (data.projects || []).map(p => `<div class="item"><b>${esc(p.name)}</b><br>${esc(p.description || '')}<br><span class="muted">${esc((p.assigned_employees || []).join(', ') || 'unassigned')}</span></div>`).join('');
      document.querySelector('#projects').innerHTML = rows || '<span class="muted">No projects yet. Run <code>marneo projects new</code>.</span>';
    }
    Promise.all([getJSON('/api/status'), getJSON('/api/employees'), getJSON('/api/projects')])
      .then(([status, employees, projects]) => { renderStatus(status); renderEmployees(employees); renderProjects(projects); })
      .catch(err => { document.querySelector('#status').textContent = err.message; });
  </script>
</body>
</html>"""


class MarneoWebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Marneo web APIs and static index."""

    server_version = "MarneoWeb/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in {"/", "/index.html"}:
                self._send_html(render_index_html())
            elif path == "/api/status":
                from marneo.web.api import build_status_payload
                self._send_json(build_status_payload())
            elif path == "/api/employees":
                from marneo.web.api import build_employees_payload
                self._send_json(build_employees_payload())
            elif path.startswith("/api/employees/"):
                from marneo.web.api import build_employee_payload
                name = unquote(path.rsplit("/", 1)[-1])
                payload = build_employee_payload(name)
                if payload is None:
                    self._send_json({"error": "employee not found"}, status=HTTPStatus.NOT_FOUND)
                else:
                    self._send_json(payload)
            elif path == "/api/projects":
                from marneo.web.api import build_projects_payload
                self._send_json(build_projects_payload())
            elif path == "/api/logs/gateway":
                from marneo.web.api import build_gateway_logs_payload
                query = parse_qs(parsed.query)
                lines = int(query.get("lines", ["200"])[0])
                self._send_json(build_gateway_logs_payload(lines=lines))
            else:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:  # defensive for local support UI
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host: str = "127.0.0.1", port: int = 8787, allow_lan: bool = False) -> None:
    """Run the local console server until interrupted."""
    bind_host = validate_bind_host(host, allow_lan=allow_lan)
    server = ThreadingHTTPServer((bind_host, int(port)), MarneoWebHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
