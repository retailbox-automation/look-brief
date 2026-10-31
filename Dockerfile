# Look Brief — public demo image (Replay mode: recorded real YouCam API results, no API key inside).
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.3 /uv /uvx /bin/
# OpenCV (pulled in by MediaPipe) needs these shared libraries at import time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY samples ./samples
RUN uv sync --frozen --no-dev
RUN useradd -m -u 10001 app && mkdir -p /data && chown app /data
USER app
# MALLOC_ARENA_MAX: glibc keeps one arena per worker thread and does not give image buffers back; two arenas bound it
ENV HOST=0.0.0.0 PORT=8080 LOOKBRIEF_DATA=/data LOOKBRIEF_LIVE=0 LOOKBRIEF_ATTEST_EPHEMERAL=1 MALLOC_ARENA_MAX=2 \
    LOOKBRIEF_TRUST_PROXY=1 LOOKBRIEF_SAMPLES=/app/samples LOOKBRIEF_PUBLIC_URL=https://lookbrief.retailbox-automation.com
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8080'),timeout=4)"
CMD ["/app/.venv/bin/lookbrief"]
