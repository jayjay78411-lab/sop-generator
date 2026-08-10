#!/usr/bin/env python3
"""Web control panel (FastAPI): orchestrate the agent browser, capture, export, and Ollama describe.

The Playwright agent is sync-API, so it must live on its own thread and never cross
into FastAPI's event loop. All access goes through a queue -> serial worker thread.
"""
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from agent_browser import AgentBrowser, CDP_ENDPOINT
from export_factory import build as export_build
from ollama_bridge import OllamaBridge

APP_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = APP_DIR / "data" / "sessions"
PANEL_HTML = APP_DIR / "web" / "panel.html"
OUT_DIR = APP_DIR / "data" / "out"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="SOP-Gen Control Panel", version="0.2.0")

CDP_URL = os.environ.get("CDP_URL", CDP_ENDPOINT)
OLLAMA = OllamaBridge()

PAGES = {}
_cmd = queue.Queue()
_resp = {}


class RecordRequest(BaseModel):
    url: str


class InteractionRequest(BaseModel):
    x: int | None = None
    y: int | None = None
    text: str | None = None
    key: str | None = None


class ExportRequest(BaseModel):
    to: str = "pdf"
    out: str | None = None


def _agent_worker():
    """Owns the sync Playwright connection; handles serialized commands."""
    agent = None
    while True:
        cmd, cid, args = _cmd.get()
        try:
            if cmd == "connect":
                agent = AgentBrowser(cdp_url=CDP_URL).connect()
                with _state["lock"]:
                    _state["connected"] = True
                _resp[cid] = {"ok": True, "connected": True, "url": CDP_URL}
            elif cmd == "open":
                page = agent.open(args["url"])
                PAGES[args["sid"]] = page
                _resp[cid] = {"ok": True, "page": True}
            elif cmd == "sweep":
                _resp[cid] = {"ok": True, "steps": agent.sweep(PAGES[args["sid"]])}
            elif cmd == "info":
                _resp[cid] = {"ok": True, "info": agent.info(PAGES[args["sid"]])}
            elif cmd == "close_page":
                try:
                    PAGES[args["sid"]].close()
                finally:
                    PAGES.pop(args["sid"], None)
                _resp[cid] = {"ok": True}
            elif cmd == "view":
                shot = agent.viewport(PAGES[args["sid"]])
                _resp[cid] = {"ok": True, "png": shot}
            elif cmd == "click":
                agent.click_at(PAGES[args["sid"]], args["x"], args["y"])
                _resp[cid] = {"ok": True, "x": args["x"], "y": args["y"]}
            elif cmd == "type":
                agent.type_text(PAGES[args["sid"]], args["text"])
                _resp[cid] = {"ok": True}
            elif cmd == "key":
                agent.press_key(PAGES[args["sid"]], args["key"])
                _resp[cid] = {"ok": True}
            elif cmd == "stop":
                break
            else:
                _resp[cid] = {"ok": False, "error": "unknown command %s" % cmd}
        except Exception as exc:
            _resp[cid] = {"ok": False, "error": str(exc)}
        finally:
            pass
    if agent:
        try:
            agent.close()
        except Exception:
            pass


def _call(cmd, payload=None, timeout=90):
    cid = uuid.uuid4().hex
    _cmd.put((cmd, cid, payload or {}))
    for _ in range(int(timeout * 10)):
        if cid in _resp:
            return _resp.pop(cid)
        time.sleep(0.1)
    raise HTTPException(504, "agent worker timed out on %s" % cmd)


def agent_connected():
    with _state["lock"]:
        return _state["connected"]


_state = {"connected": False, "lock": threading.Lock()}

_thread = threading.Thread(target=_agent_worker, daemon=True)
_thread.start()


@app.on_event("startup")
def _startup():
    for attempt in range(15):
        r = _call("connect", timeout=15)
        if r.get("ok"):
            print("Agent browser connected to", CDP_URL)
            return
        if attempt < 14:
            print("agent connect attempt %d failed: %s (retrying)" % (attempt + 1, r.get("error")))
            time.sleep(2)
    print("Agent browser NOT connected:", r.get("error"))


@app.on_event("shutdown")
def _shutdown():
    try:
        _call("stop", timeout=5)
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(PANEL_HTML.read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    ollama = None
    try:
        ollama = bool(OLLAMA.available())
    except Exception:
        pass
    return {
        "ok": True,
        "agent_connected": agent_connected(),
        "ollama_available": bool(ollama),
        "ollama_model": OLLAMA.model,
        "sessions": [k for k in PAGES.keys()],
    }


@app.post("/api/record/start")
def record_start(req: RecordRequest):
    sid = "sop-" + uuid.uuid4().hex[:8]
    r = _call("open", {"sid": sid, "url": req.url})
    if not r.get("ok"):
        raise HTTPException(502, "failed to open URL: %s" % r.get("error"))
    return {"sessionId": sid, "url": req.url}


@app.get("/api/record/{sid}/viewport.png")
def record_viewport(sid: str):
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    try:
        shot = _call("view", {"sid": sid}).get("png")
    except Exception as exc:
        raise HTTPException(502, "viewport failed: %s" % exc)
    return Response(content=shot, media_type="image/png")


@app.post("/api/record/{sid}/click")
def record_click(sid: str, req: InteractionRequest):
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    if req.x is None or req.y is None:
        raise HTTPException(422, "x and y required")
    try:
        r = _call("click", {"sid": sid, "x": req.x, "y": req.y})
    except Exception as exc:
        raise HTTPException(502, "click failed: %s" % exc)
    return {"ok": True, "x": r.get("x"), "y": r.get("y")}


@app.post("/api/record/{sid}/type")
def record_type(sid: str, req: InteractionRequest):
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    if not req.text:
        raise HTTPException(422, "text required")
    try:
        _call("type", {"sid": sid, "text": req.text})
    except Exception as exc:
        raise HTTPException(502, "type failed: %s" % exc)
    return {"ok": True}


@app.post("/api/record/{sid}/key")
def record_key(sid: str, req: InteractionRequest):
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    if not req.key:
        raise HTTPException(422, "key required")
    try:
        _call("key", {"sid": sid, "key": req.key})
    except Exception as exc:
        raise HTTPException(502, "key failed: %s" % exc)
    return {"ok": True}


@app.post("/api/record/{sid}/stop")
def record_stop(sid: str):
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    r = _call("sweep", {"sid": sid})
    steps = r.get("steps", [])
    payload = {
        "sessionId": sid,
        "exportedAt": time.time(),
        "steps": steps,
        "url": PAGES[sid].url if PAGES[sid] else None,
    }
    out = SESSIONS_DIR / (sid + ".json")
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _call("close_page", {"sid": sid})
    return {"sessionId": sid, "closed": True, "steps": len(steps), "saved": str(out)}


@app.get("/api/record/{sid}/steps")
def record_steps(sid: str):
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    r = _call("sweep", {"sid": sid})
    return {"sessionId": sid, "steps": r.get("steps", [])}


@app.post("/api/record/{sid}/finalize")
def finalize(sid: str, body: ExportRequest):
    """Drain current steps into a named session file (without touching the live page)."""
    if sid not in PAGES:
        raise HTTPException(404, "no such active session")
    r = _call("sweep", {"sid": sid})
    payload = {"sessionId": sid, "exportedAt": time.time(), "steps": r.get("steps", [])}
    out = SESSIONS_DIR / (sid + ".json")
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"sessionId": sid, "steps": len(payload["steps"]), "saved": str(out)}


@app.post("/api/export/{sid}")
def session_export(sid: str, body: ExportRequest):
    path = SESSIONS_DIR / (sid + ".json")
    if not path.exists():
        raise HTTPException(404, "session file not found")
    try:
        result = export_build(str(path), body.to, canvas_cfg(), body.out or str(OUT_DIR))
    except Exception as exc:
        raise HTTPException(500, "export failed: %s" % exc)
    return {"ok": True, "result": result}


@app.get("/api/export/{sid}/download")
def session_export_download(sid: str, to: str = "pdf"):
    path = SESSIONS_DIR / (sid + ".json")
    if not path.exists():
        raise HTTPException(404, "session file not found")
    try:
        result = export_build(str(path), to, canvas_cfg(), str(OUT_DIR))
    except Exception as exc:
        raise HTTPException(500, "export failed: %s" % exc)
    if to == "pdf":
        fpath = result.get("path")
        if not fpath or not Path(fpath).exists():
            raise HTTPException(500, "pdf not generated")
        return Response(
            content=Path(fpath).read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="%s.pdf"' % sid},
        )
    if to == "editor":
        return Response(
            content=json.dumps(result.get("steps", []), indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="%s.json"' % sid},
        )
    path = result.get("path")
    if path and Path(path).exists():
        return Response(
            content=Path(path).read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="%s.pdf"' % sid},
        )
    return {"ok": True, "result": result}


@app.post("/api/describe/{sid}")
def describe(sid: str):
    path = SESSIONS_DIR / (sid + ".json")
    if not path.exists():
        raise HTTPException(404, "session file not found")
    session = json.loads(path.read_text(encoding="utf-8"))
    try:
        text = OLLAMA.describe_session(session.get("steps", []), sid)
    except Exception as exc:
        raise HTTPException(502, "Ollama call failed: %s" % exc)
    return {"sessionId": sid, "description": text}


@app.get("/api/sessions")
def list_sessions():
    out = []
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"sessionId": data.get("sessionId"), "steps": len(data.get("steps", [])), "file": str(f)})
    return {"sessions": out}


def canvas_cfg():
    url = os.environ.get("CANVAS_API_URL")
    token = os.environ.get("CANVAS_API_TOKEN")
    course = os.environ.get("CANVAS_COURSE_ID")
    if url and token and course:
        return {"api_url": url, "token": token, "course_id": course}
    return None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PANEL_PORT", "8000")))