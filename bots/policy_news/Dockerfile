FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POLICY_NEWS_ENABLED=false \
    POLICY_NEWS_DRY_RUN=true

WORKDIR /app/bots/policy_news

COPY requirements-runtime.txt ./requirements-runtime.txt
RUN pip install -r requirements-runtime.txt

COPY . ./

RUN useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app
USER 10001

ENTRYPOINT ["python", "scheduled_job.py"]
