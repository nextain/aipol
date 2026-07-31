FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVENT_ENV=production \
    EVENT_DEMO_ENABLED=false \
    EVENT_DB_PATH=/data/event.db \
    EVENT_ROSTER_PATH=/data/roster.json \
    EVENT_SQLITE_NOLOCK=true

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data
COPY . .
# Azure Files(SMB) 마운트는 ACA에서 uid/gid 매핑을 제공하지 않아 쓰기 프로세스는 root로 실행한다.
# 앱은 단일 목적 컨테이너이며 외부 명령 실행·업로드 경로를 제공하지 않는다.
EXPOSE 8100
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1", "--no-proxy-headers"]
