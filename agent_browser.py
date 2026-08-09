#!/usr/bin/env python3
import argparse
import json
import os
import time

from pathlib import Path

BRIDGE_SRC = Path(__file__).resolve().parent / "browser_storage.js"
CDP_ENDPOINT = os.environ.get("CDP_URL", "http://127.0.0.1:9222")


class AgentBrowser:
    def __init__(self, cdp_url=CDP_ENDPOINT, persist_dir=None):
        self.cdp_url = cdp_url
        self.persist_dir = Path(persist_dir) if persist_dir else Path(__file__).resolve().parent / "data"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.bridge = BRIDGE_SRC.read_text(encoding="utf-8")
        self._pw = None
        self.browser = None
        self.context = None

    def connect(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        self.context = self.browser.contexts[0]
        return self

    def open(self, url):
        page = self.context.new_page()
        page.add_init_script(self.bridge)
        page.goto(url, wait_until="domcontentloaded")
        return page

    def inject(self, page):
        page.evaluate("({})".format(self.bridge))

    def sweep(self, page):
        return page.evaluate("() => window.__sopGet()")

    def info(self, page):
        return page.evaluate("() => window.__sopInfo()")

    def shot(self, page, session_id, index, viewport_only=True):
        """Capture the current browser screen view for a session step (synchronous)."""
        snap_dir = self.persist_dir / "shots" / (session_id or "anon")
        snap_dir.mkdir(parents=True, exist_ok=True)
        fname = "%04d.png" % index
        path = snap_dir / fname
        page.screenshot(path=str(path), full_page=not viewport_only)
        return str(path)

    def watch(self, page, session_id, poll=1.0, deadline=None, on_step=None):
        """Screen-capture recorder: save a PNG whenever a new step is recorded."""
        last = len(self.sweep(page))
        index = last
        count = 0
        while True:
            if deadline is not None and time.time() >= deadline:
                break
            steps = self.sweep(page)
            n = len(steps)
            while n > last:
                path = self.shot(page, session_id, index + 1)
                count += 1
                if on_step:
                    on_step(index + 1, steps[last:last + 1], path)
                last += 1
                index += 1
            time.sleep(poll)
        return count

    def export(self, page, session_id=None):
        steps = self.sweep(page)
        info = self.info(page) or {}
        sid = session_id or info.get("sessionId")
        shot_dir = self.persist_dir / "shots" / (sid or "anon")
        payload = {
            "sessionId": sid,
            "exportedAt": time.time(),
            "steps": steps,
        }
        if shot_dir.exists():
            payload["shotsBase"] = str(shot_dir)
            payload["shotCount"] = len(list(shot_dir.glob("*.png")))
        out = self.persist_dir / "sessions" / (payload["sessionId"] + ".json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(out)

    def close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()


def main():
    ap = argparse.ArgumentParser(description="Playwright agent browser over CDP (Xvfb Chrome)")
    ap.add_argument("--url", default="http://example.com")
    ap.add_argument("--cdp", default=CDP_ENDPOINT)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--persist", default=None)
    ap.add_argument("--watch", action="store_true", help="capture screenshots as steps are recorded")
    ap.add_argument("--seconds", type=int, default=30, help="how long to watch before exporting")
    ap.add_argument("--full", action="store_true", help="full-page screenshots instead of viewport")
    args = ap.parse_args()

    agent = AgentBrowser(cdp_url=args.cdp, persist_dir=args.persist)
    agent.connect()
    page = None
    try:
        page = agent.open(args.url)
        if args.watch:
            sid = "sop-" + time.strftime("%Y%m%d%H%M%S")
            print("Watching for interactions; capturing screenshots for %ss..." % args.seconds)
            deadline = time.time() + args.seconds
            agent.watch(page, sid, poll=0.5, deadline=deadline, on_step=lambda i, s, p: print("  shot %d -> %s" % (i, p)))
            json_path = agent.export(page, sid)
            shot_dir = agent.persist_dir / "shots" / sid
            shot_count = len(list(shot_dir.glob("*.png"))) if shot_dir.exists() else 0
            print("Captured {} steps, {} viewshots -> {}".format(len(agent.sweep(page)), shot_count, json_path))
        else:
            input("Recording. Interact with the page, then press Enter to stop...")
            json_path = agent.export(page)
            if args.dump:
                print("Session file:", json_path)
            print("Captured {} interaction steps -> {}".format(agent.info(page).get("stepCount"), json_path))
        print("Events: click/input registered in Chrome localStorage (window.__sopGet).")
    finally:
        if page:
            page.close()
        agent.close()


if __name__ == "__main__":
    main()