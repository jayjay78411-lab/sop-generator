#!/bin/bash
set -e

export DISPLAY=:99
rm -f /tmp/.X99-lock

Xvfb :99 -screen 0 1280x800x24 -ac >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
sleep 2

mkdir -p /opt/chrome-profile
rm -f /opt/chrome-profile/SingletonLock /opt/chrome-profile/SingletonSocket /opt/chrome-profile/SingletonCookie

google-chrome \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --remote-debugging-port=9222 \
    --remote-debugging-address=0.0.0.0 \
    --user-data-dir=/opt/chrome-profile \
    --window-size=1280,800 \
    about:blank >/tmp/chrome.log 2>&1 &
CHROME_PID=$!

echo "Xvfb PID=$XVFB_PID Chrome PID=$CHROME_PID DISPLAY=$DISPLAY"
echo "Chrome CDP available at http://127.0.0.1:9222"

python3 /app/web_control_panel.py >/tmp/panel.log 2>&1 &
PANEL_PID=$!
echo "Control panel PID=$PANEL_PID on 0.0.0.0:8000"

cleanup() {
    kill "$PANEL_PID" "$CHROME_PID" "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT

wait "$CHROME_PID"