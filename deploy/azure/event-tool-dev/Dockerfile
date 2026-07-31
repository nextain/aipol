FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVENT_ENV=production \
    EVENT_DEMO_ENABLED=false \
    EVENT_DB_PATH=/data/event.db \
    EVENT_ROSTER_PATH=/data/roster.json \
    EVENT_SQLITE_NOLOCK=true

WORKDIR /app

COPY event-tool/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && groupadd --gid 10001 aipol \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin aipol \
    && install -d -o 10001 -g 10001 -m 0750 /data

# server.py imports both event-tool modules and the repository-level policy_lab
# package. Keep this Dockerfile's build context at the repository root.
COPY event-tool/*.py ./
COPY event-tool/web ./web
COPY event-tool/instances ./instances
COPY policy_lab ./policy_lab
COPY deploy/azure/event-tool-dev/serialized_app.py ./serialized_app.py
COPY deploy/azure/event-tool-dev/backup_sqlite.py ./backup_sqlite.py

RUN python -m compileall -q /app

EXPOSE 8100

USER 10001:10001

CMD ["uvicorn", "serialized_app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1", "--no-proxy-headers"]
