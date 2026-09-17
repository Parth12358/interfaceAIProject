"""Minimal FastAPI operator console — mocked UI, real control-transfer mechanism.

Endpoints:
  GET  /            HTML page: current state + intervention request + buttons
  GET  /state       JSON snapshot
  POST /escalate    (simulated) the engine raises an intervention request here
  POST /take        operator takes control of the live session
  POST /handback    operator hands control back
  POST /resume      engine re-classifies; body {recognized: bool}
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from .control import ControlSession, InterventionRequest

app = FastAPI(title="CoreServ Operator Console")
SESSION = ControlSession()


@app.get("/state")
def state():
    return JSONResponse(SESSION.snapshot())


@app.post("/escalate")
def escalate(payload: dict):
    req = InterventionRequest(
        capability_id=payload.get("capability_id", "unknown"),
        version=payload.get("version", "1.0.0"),
        step_id=payload.get("step_id"),
        reason=payload.get("reason", "stuck"),
        observed=payload.get("observed", []),
        screenshot_path=payload.get("screenshot_path"),
        log_tail=payload.get("log_tail", []),
    )
    SESSION.escalate(req)
    return SESSION.snapshot()


@app.post("/take")
def take():
    SESSION.take_control()
    return SESSION.snapshot()


@app.post("/handback")
def handback():
    SESSION.hand_back()
    return SESSION.snapshot()


@app.post("/resume")
def resume(payload: dict):
    SESSION.resume(bool(payload.get("recognized", True)))
    return SESSION.snapshot()


@app.get("/", response_class=HTMLResponse)
def index():
    s = SESSION.snapshot()
    req = s["request"]
    req_html = "<p><i>No active intervention.</i></p>"
    if req:
        req_html = (
            f"<ul>"
            f"<li><b>Capability:</b> {req['capability_id']} v{req['version']}</li>"
            f"<li><b>Step:</b> {req['step_id']}</li>"
            f"<li><b>Reason:</b> {req['reason']}</li>"
            f"<li><b>Observed:</b> {', '.join(req['observed']) or '—'}</li>"
            f"</ul>"
            f"<pre>{chr(10).join(req['log_tail'][-8:])}</pre>"
        )
    return f"""
    <html><head><title>Operator Console</title>
    <meta http-equiv="refresh" content="3">
    <style>body{{font-family:system-ui;margin:2rem;max-width:640px}}
    button{{padding:.5rem 1rem;margin-right:.5rem}} .s{{font-weight:700}}</style></head>
    <body>
      <h2>CoreServ Operator Console</h2>
      <p>State: <span class="s">{s['state']}</span> &nbsp; Controller: <b>{s['holder'] or '—'}</b></p>
      <h3>Intervention request</h3>
      {req_html}
      <form method="post" action="/take"><button {'disabled' if s['state']!='ESCALATED' else ''}>Take control</button></form>
      <form method="post" action="/handback"><button {'disabled' if s['state']!='HUMAN_CONTROL' else ''}>Hand back</button></form>
      <p style="color:#666">Mocked UI; the state machine + single-controller token are real.
      While the human holds control, automation emits zero input.</p>
    </body></html>
    """
