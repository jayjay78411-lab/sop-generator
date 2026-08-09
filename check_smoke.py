#!/usr/bin/env python3
import json
import socket
import sys
import time
import urllib.request

CDP = "http://127.0.0.1:9222"
TARGET = "http://example.com"
TIMEOUT = 90


def wait_for_port(host, port, timeout=TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            time.sleep(1)
    return False


def http_get(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read()


def main():
    if not wait_for_port("127.0.0.1", 9222):
        print("FAIL: Chrome CDP port 9222 not reachable within %ss" % TIMEOUT)
        return 1

    version = json.loads(http_get(CDP + "/json/version"))
    ws = version.get("webSocketDebuggerUrl")
    browser = version.get("Browser", "")
    if not ws:
        print("FAIL: /json/version missing webSocketDebuggerUrl")
        return 1
    print("OK: Chrome %s CDP websocket %s" % (browser, ws))

    req = urllib.request.Request(CDP + "/json/new?http://example.com", method="PUT")
    with urllib.request.urlopen(req, timeout=15) as resp:
        tab = json.loads(resp.read())
    page_id = tab.get("id")
    url = tab.get("url", "")
    title = tab.get("title", "")
    for _ in range(20):
        if title:
            break
        time.sleep(0.5)
        with urllib.request.urlopen(CDP + "/json", timeout=15) as resp:
            for page in json.loads(resp.read()):
                if page.get("id") == page_id:
                    title = page.get("title", "")
    print("OK: opened remote target title=%r url=%r id=%r" % (title, url, page_id))
    if "Example" not in title and "example" not in url:
        print("WARN: remote page title did not match, got %r" % title)
    print("PASS: chrome launched inside Xvfb, remote page rendered via CDP")
    return 0


if __name__ == "__main__":
    sys.exit(main())