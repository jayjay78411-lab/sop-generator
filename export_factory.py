#!/usr/bin/env python3
"""Export factory: route recorded SOP session JSON to PDF / Canvas LMS / editable array."""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from fpdf import FPDF
    HAVE_FPDF = True
except ImportError:
    HAVE_FPDF = False

try:
    from canvasapi import Canvas
    HAVE_CANVASAPI = True
except ImportError:
    HAVE_CANVASAPI = False


def load_session(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"sessionId": "mock", "steps": data}
    return data


def format_for_editor(session):
    steps = session.get("steps", []) if isinstance(session, dict) else session
    return [
        {
            "index": i,
            "type": s.get("type", "step"),
            "selector": s.get("selector"),
            "url": s.get("url"),
            "text": s.get("text"),
            "value": s.get("value"),
            "ts": s.get("ts"),
            "osuosl": None,
        }
        for i, s in enumerate(steps)
    ]


def _bare_pdf(title, steps):
    """Dependency-free minimal PDF (Helvetica): used when fpdf2 is unavailable."""
    content = "BT /F1 16 Tf 40 780 Td (%s) Tj ET\n" % _esc(title)
    y = 740
    for i, s in enumerate(steps[:8]):
        line = "STEP %d | %s | %s" % (i + 1, s.get("type"), s.get("selector"))
        content += "BT /F1 10 Tf 40 %d Td (%s) Tj ET\n" % (y, _esc(line))
        y -= 24
        if y < 40:
            break
    stream = content.encode("latin-1")
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj",
        b"4 0 obj<</Length %d>>stream\n" % len(stream) + stream + b"\nendstreamendobj",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
    ]
    return _assemble(objects)


def _assemble(objects):
    body = b""
    offsets = []
    for i, o in enumerate(objects, 1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref_start = len(b"%PDF-1.4\n") + len(body)
    xref = b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        xref += ("%010d 00000 n \n" % off).encode("ascii")
    trailer = b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref_start + len(xref))
    return b"%PDF-1.4\n" + body + xref + trailer


def _esc(text):
    clean = "".join(c for c in str(text) if 32 <= ord(c) < 127)
    return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:200]


def generate_pdf(session, output_dir):
    title = "SOP Session %s" % session.get("sessionId", "unknown")
    out = Path(output_dir) / ("sop_%s.pdf" % session.get("sessionId", "unknown"))
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    shots = sorted((Path(session.get("shotsBase", "")) or _shots_dir(session)).glob("*.png")) if HAVE_FPDF else []

    if HAVE_FPDF:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, title)
        pdf.ln()
        pdf.set_font("Helvetica", "", 10)
        for i, s in enumerate(session.get("steps", [])):
            pdf.multi_cell(0, 5, "STEP %s | %s\n%s\n%s" % (s.get("type"), s.get("selector"), s.get("url"), (s.get("text") or "")[:120]))
            if i < len(shots):
                pdf.ln(1)
                try:
                    pdf.image(str(shots[i]), w=pdf.epw)
                except Exception:
                    pass
            pdf.ln(1)
        pdf.output(str(out))
    else:
        out.write_bytes(_bare_pdf(title, session.get("steps", [])))
    return str(out)


def _shots_dir(session):
    base = Path(__file__).resolve().parent / "data" / "shots" / (session.get("sessionId") or "anon")
    return base if base.exists() else Path(__file__).resolve().parent / "data"


def push_to_canvas(api_url, api_token, course_id, file_path):
    """Upload a PDF into Canvas Files as multipart/form-data."""
    filename = os.path.basename(file_path)
    content = Path(file_path).read_bytes()

    if HAVE_CANVASAPI:
        canvas = Canvas(api_url, api_token)
        course = canvas.get_course(course_id)
        upload = course.upload_file(file_path, content_type="application/pdf")
        return {"canvasapi": True, "result": upload}

    boundary = "----sop-%d" % int(time.time() * 1000)
    buf = []
    buf.append(("--%s\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n%s\r\n" % (boundary, filename)).encode())
    buf.append(("--%s\r\nContent-Disposition: form-data; name=\"content_type\"\r\n\r\napplication/pdf\r\n" % boundary).encode())
    buf.append(("--%s\r\nContent-Disposition: form-data; name=\"attachment\"; filename=\"%s\"\r\nContent-Type: application/pdf\r\n\r\n" % (boundary, filename)).encode())
    buf.append(content)
    buf.append(("--%s--\r\n" % boundary).encode())
    body = b"".join(buf)

    url = urllib.parse.urljoin(api_url.rstrip("/") + "/", "api/v1/courses/%s/files" % course_id)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + api_token)
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return {"canvasapi": False, "status": resp.status, "body": resp.read().decode()[:800]}
    except urllib.error.HTTPError as e:
        return {"canvasapi": False, "status": e.code, "error": e.read().decode()[:800]}


def build(session_path, choice, canvas=None, out_dir=None):
    session = load_session(session_path)
    out_dir = out_dir or str(Path(session_path).parent)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    if choice == "editor":
        return {"mode": "editor", "sessionId": session.get("sessionId"), "steps": format_for_editor(session)}
    if choice == "pdf":
        path = generate_pdf(session, out_dir)
        return {"mode": "pdf", "path": path, "bytes": os.path.getsize(path), "steps": len(session.get("steps", []))}
    if choice == "canvas":
        path = generate_pdf(session, out_dir)
        if not canvas or not all(k in canvas for k in ("api_url", "token", "course_id")):
            return {"mode": "canvas", "error": "canvas credentials required (api_url, token, course_id)", "staged_pdf": path}
        result = push_to_canvas(canvas["api_url"], canvas["token"], canvas["course_id"], path)
        return {"mode": "canvas", "result": result, "path": path}
    raise ValueError("mode must be one of: editor, pdf, canvas")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="SOP export factory (PDF/Canvas/Editor)")
    ap.add_argument("session")
    ap.add_argument("--to", choices=["editor", "pdf", "canvas"], default="pdf")
    ap.add_argument("--out", default=None)
    canvas_group = ap.add_argument_group("canvas")
    canvas_group.add_argument("--api-url", default=os.environ.get("CANVAS_API_URL"))
    canvas_group.add_argument("--api-token", default=os.environ.get("CANVAS_API_TOKEN"))
    canvas_group.add_argument("--course", default=os.environ.get("CANVAS_COURSE_ID"))
    args = ap.parse_args()

    canvas_cfg = None
    if args.api_url and args.api_token and args.course:
        canvas_cfg = {"api_url": args.api_url, "token": args.api_token, "course_id": args.course}

    result = build(args.session, args.to, canvas_cfg, args.out)
    print(json.dumps({"ok": True, "result": result}, indent=2, default=str))