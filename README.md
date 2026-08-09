# SOP Generator — Server-Side Chrome Container (STEP 1)

Containerized Google Chrome + Xvfb environment for the SOP Generator, built for
Proxmox VE (LXC or Docker VM) but works on any Docker host.

## Files
- `Dockerfile` — debian:bookworm-slim + Node 20/Python 3.12 + google-chrome-stable + Xvfb + deps from `requirements.txt`
- `docker/entrypoint.sh` — starts Xvfb `:99`, launches Chrome on CDP port 9222, runs the FastAPI panel on :8000
- `check_smoke.py` — stdlib-only validator: CDP `/json/version` + remote page render check
- `docker-compose.yml` — services `sgen` + `ollama` on bridge `sopnet`, volume `chrome-profile` (persists localStorage), ports 9222/8000
- `agent_browser.py` — Playwright agent (CDP connect, inject, record, `--watch` screen capture, export)
- `browser_storage.js` — injected telemetry: click/input → CSS selector + URL + timestamp into Chrome `localStorage`
- `export_factory.py` — routes session JSON to PDF (fpdf2 + screenshots), Canvas LMS (multipart), or editable array
- `ollama_bridge.py` — `qwen2.5-instruct` client (httpx with urllib fallback)
- `web_control_panel.py` + `web/panel.html` — FastAPI control panel UI (record/export/describe)
- `deploy_pve.sh` — one-shot deployment on a Proxmox/Docker host

## Proxmox deployment
```bash
# copy this project to the host (git clone or scp), then:
bash deploy_pve.sh /opt/sopgen
# or step-by-step:
docker compose up -d --build
docker compose exec sgen python3 /app/check_smoke.py
docker compose exec ollama ollama pull qwen2.5-instruct
# open http://<proxmox-host>:8000
```

## Expected smoke output
```
OK: Chrome ... CDP websocket ws://...
OK: opened remote target title='Example Domain' ...
PASS: chrome launched inside Xvfb, remote page rendered via CDP
```

## Record a session
```bash
# interactive: interact, press Enter
docker compose exec sgen python3 /app/agent_browser.py --url http://example.com
# watch mode: screenshot per interaction step for N seconds, then auto-export
docker compose exec sgen python3 /app/agent_browser.py --url http://example.com --watch --seconds 60
# full-page screenshots instead of viewport
docker compose exec sgen python3 /app/agent_browser.py --url http://example.com --watch --full
```
Screenshots land in `data/shots/<session>/NNNN.png`; the session JSON carries `shotsBase`, and
`export_factory --to pdf` embeds them per-step (validated: 829 B -> 15 KB PDF).

## CI (GitHub Actions)
On push/PR touching `Dockerfile`, compose, or sources, `.github/workflows/ci.yml` builds the image
on ubuntu-latest, runs the Xvfb Chrome smoke test (`check_smoke.py`), then unit-checks the export
factory — no user Docker host required.

## Export routes (tested against real session + mock Canvas server)
```bash
docker compose exec sgen python3 /app/export_factory.py /app/data/sessions/<id>.json --to pdf --out /app/data/out
docker compose exec sgen python3 /app/export_factory.py /app/data/sessions/<id>.json --to editor
docker compose exec sgen python3 /app/export_factory.py /app/data/sessions/<id>.json --to canvas \
  --api-url $CANVAS_API_URL --api-token $CANVAS_API_TOKEN --course $CANVAS_COURSE_ID
```

## Web control panel + AI describe (Phase 2)
The container runs the FastAPI panel on port 8000 alongside Xvfb Chrome; Ollama runs as a
compose service (`qwen2.5-instruct`).

```bash
# 1. pull the model into the ollama container
docker compose exec ollama ollama pull qwen2.5-instruct
# 2. open the control panel
#    http://<host>:8000   (record URL, stop & save, export, auto-describe via Ollama)
# REST API:
#   GET  /api/health
#   POST /api/record/start            {"url": "http://example.com"}
#   GET  /api/record/<sid>/steps
#   POST /api/record/<sid>/finalize    -> session JSON
#   POST /api/export/<sid>            {"to": "pdf"|"editor"|"canvas"}
#   POST /api/describe/<sid>          -> AI-written procedure via Ollama bridge
```

## Manual inspection
- Chrome DevTools: `http://<host>:9222` (CDP HTTP) or connect websocket `ws://<host>:9222/devtools/browser/<id>`
- View the virtual display: run Xvfb with VNC or use `x11vnc -display :99 &` then connect to port 5900.

## Proxmox notes
- No GPU needed — SwiftShader software rendering (`--disable-gpu`).
- Persisted browser storage lives in the `chrome-profile` named volume (localStorage/IndexedDB survive restarts).
- Change `OLLAMA_HOST` in `docker-compose.yml` to point at your Ollama instance (`http://<ollama-ip>:11434`).