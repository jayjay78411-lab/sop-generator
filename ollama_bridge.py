#!/usr/bin/env python3
"""Ollama bridge: internal-network client for a headless qwen2.5:3b instance."""
import json
import os
import time

try:
    import httpx

    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

try:
    import urllib.request as _ur
except ImportError:  # pragma: no cover
    _ur = None

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")


class OllamaBridge:
    def __init__(self, host=DEFAULT_HOST, model=MODEL, timeout=900):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self):
        try:
            self._get("/api/tags")
            return True
        except Exception:
            return False

    def generate(self, prompt, system=None, options=None):
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        out = self._post("/api/generate", payload)
        return out.get("response", "")

    def describe_session(self, steps, session_id=None):
        brief = []
        for s in steps or []:
            detail = " ".join(x for x in [s.get("url"), s.get("selector"), (s.get("text") or "")[:80]] if x)
            brief.append("- [%s] %s" % (s.get("type", "step"), detail))
        system = (
            "You are an SOP writer. Convert recorded browser interaction steps into clear, "
            "numbered procedural instructions. Use the exact past tense of the action. "
            "Return plain Markdown, no preamble, no extra commentary."
        )
        prompt = "Recorded session%s:\n%s\n\nWrite the step-by-step procedure:" % (
            (" " + session_id) if session_id else "",
            "\n".join(brief[:40]) or "(no steps recorded)",
        )
        return self.generate(prompt, system=system)

    def _post(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
        return self._request(path, body, method="POST")

    def _get(self, path):
        return self._request(path, None, method="GET")

    def _request(self, path, body, method):
        url = self.host + path
        if _HAS_HTTPX:
            with httpx.Client(timeout=self.timeout) as client:
                if method == "POST":
                    resp = client.post(url, content=body, headers={"Content-Type": "application/json"})
                else:
                    resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        if not _ur:
            raise RuntimeError("httpx or urllib required")
        req = _ur.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        with _ur.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Ollama bridge smoke test (qwen2.5:3b)")
    ap.add_argument("--session", default=None)
    ap.add_argument("--steps", default="data/sessions")
    args = ap.parse_args()

    bridge = OllamaBridge()
    print("available=", bridge.available())
    print("ping reply:\n", bridge.generate("Reply with exactly: OK").strip() or "(empty)")