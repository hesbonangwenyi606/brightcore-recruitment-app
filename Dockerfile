FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    BRIGHTCORE_DB=/data/brightcore.sqlite3 \
    BRIGHTCORE_UPLOADS=/data/private_uploads

WORKDIR /app

COPY server.py index.html app.js style.css ./

RUN mkdir -p /data/private_uploads \
    && useradd --system --uid 10001 --no-create-home app \
    && chown -R app:app /app /data

USER app

EXPOSE 8000

CMD ["python", "server.py"]
