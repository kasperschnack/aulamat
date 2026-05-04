FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    AULA_TOKEN_CACHE_PATH=/data/.aula_tokens.json \
    AULA_SCAN_STATE_PATH=/data/.aula_scan_state.json \
    AULA_RAW_CAPTURE_DIR=/data/.aula_raw

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked --no-dev

RUN mkdir -p /data

EXPOSE 8767

CMD ["aula-project", "summary-server", "--host", "0.0.0.0", "--port", "8767", "--thread-limit", "20", "--limit", "10"]
