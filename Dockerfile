FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY prvsmsbot /app/prvsmsbot
COPY scripts /app/scripts

RUN chmod +x /app/scripts/run.sh && pip install --no-cache-dir .

CMD ["/app/scripts/run.sh"]
