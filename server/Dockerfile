FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY pyproject.toml .
COPY app ./app
# Flutter web build (from app/build/web), served at /
COPY web ./web
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home kasita && mkdir -p /data/uploads && chown kasita /data/uploads

USER kasita
ENV KASITA_UPLOAD_DIR=/data/uploads
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
