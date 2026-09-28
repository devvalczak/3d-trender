# syntax=docker/dockerfile:1
# 3D Trender: obraz działający na Linux, macOS (Intel i Apple Silicon) i Windows (Docker Desktop).
# python:3.12-slim jest wieloarchitekturowy (amd64 + arm64), więc Docker sam wybierze właściwy wariant.

FROM python:3.12-slim AS build
# pytrends (nieoficjalne Google Trends) jest opcjonalne i ciągnie pandas: --build-arg WITH_PYTRENDS=true
ARG WITH_PYTRENDS=false
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY trender ./trender
RUN if [ "$WITH_PYTRENDS" = "true" ]; then pip install ".[pytrends]"; else pip install .; fi

FROM python:3.12-slim
LABEL org.opencontainers.image.title="3d-trender" \
      org.opencontainers.image.description="Trendy, konkurencja, modele i kalkulacja kosztów dla sprzedaży wydruków 3D" \
      org.opencontainers.image.source="https://github.com/devvalczak/3d-trender"
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DB_PATH=/app/data/trender.db
RUN useradd --create-home --uid 10001 trender \
    && mkdir -p /app/data && chown trender:trender /app/data
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER trender
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/status', timeout=4)"
CMD ["3d-trender"]
