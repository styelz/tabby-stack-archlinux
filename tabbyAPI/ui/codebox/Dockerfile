FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
        python3 \
        python3-pip \
    && PIP_BREAK_SYSTEM_PACKAGES=1 pip3 install --no-cache-dir "python-lsp-server" \
    && npm install -g --omit=dev typescript-language-server vscode-langservers-extracted \
    && rm -rf /var/lib/apt/lists/* /root/.npm /root/.cache

WORKDIR /work
CMD ["sleep", "infinity"]
