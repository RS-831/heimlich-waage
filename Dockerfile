FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
# Code für alle lesbar machen, unabhängig von den Dateirechten auf dem Host
# (Dateien mit Modus 600 wären für den Nutzer "app" sonst nicht lesbar)
RUN chmod -R a+rX /srv

# Nicht als root laufen; UID/GID per Build-Arg anpassbar (z. B. an NAS-Nutzer)
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} app && useradd -u ${UID} -g ${GID} -M app \
    && mkdir -p /data && chown app:app /data
USER app

VOLUME ["/data"]
EXPOSE 8000

WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
