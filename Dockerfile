# One image, two processes: python -m subs.worker and python -m subs.gateway (docker-compose.yml).
FROM python:3.12.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY sessions.yaml ./
COPY samples/audio ./samples/audio
COPY scripts/replay_events.py ./scripts/replay_events.py

RUN useradd --create-home --uid 1000 subs
USER subs
