FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        gnupg \
        unzip \
        jq \
        python3 \
        python3-pip \
        nodejs \
        npm \
        xvfb \
        xauth \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        fonts-liberation \
        fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/google-chrome.deb \
    && rm -f /tmp/google-chrome.deb \
    && google-chrome --version

ENV HOME=/root
ENV DISPLAY=:99
WORKDIR /app

COPY docker/entrypoint.sh /docker/entrypoint.sh
COPY check_smoke.py /app/check_smoke.py
COPY agent_browser.py browser_storage.js export_factory.py ollama_bridge.py web_control_panel.py /app/
COPY web/panel.html /app/web/panel.html
COPY requirements.txt /app/requirements.txt
RUN chmod +x /docker/entrypoint.sh \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && playwright install-deps chromium

ENTRYPOINT ["/docker/entrypoint.sh"]