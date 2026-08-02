FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --gid 10001 timeline && useradd --uid 10001 --gid timeline --no-create-home timeline
COPY pyproject.toml README.md ./
COPY backend ./backend
# hadolint ignore=DL3013
RUN python -m pip install --upgrade "pip==26.1.2" && python -m pip install .
RUN mkdir -p /var/lib/timeline-cti /models/cti /backups && chown -R timeline:timeline /var/lib/timeline-cti /models /backups

USER timeline
EXPOSE 8000

FROM base AS api
CMD ["uvicorn", "timeline_cti.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]

FROM base AS collector
USER root
# hadolint ignore=DL3013
RUN python -m pip install ".[browser]"
USER timeline
CMD ["python", "-m", "timeline_cti.collector"]

FROM base AS worker-base
CMD ["python", "-m", "timeline_cti.worker"]

FROM base AS worker
USER root
# hadolint ignore=DL3013
RUN python -m pip install ".[ml]"
USER timeline
CMD ["python", "-m", "timeline_cti.worker"]

FROM worker AS model-init
CMD ["python", "-m", "timeline_cti.model_init"]

FROM base AS benchmark
CMD ["python", "-m", "timeline_cti.benchmark", "--rows", "1000000"]
