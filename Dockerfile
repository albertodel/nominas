# Nóminas — imagen para Raspberry Pi 5 (arm64) o cualquier x86_64
FROM python:3.12-slim

LABEL org.opencontainers.image.description="Nóminas: lectura de PDF de A3 y panel de cobros, IRPF y Seguridad Social"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data TZ=Europe/Madrid

# poppler-utils = pdftotext (lectura de los PDF de A3)
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

RUN useradd -u 1000 -m app && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
