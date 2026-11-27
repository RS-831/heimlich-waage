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

# Die App läuft als Nutzer "app" (UID/GID per Build-Arg anpassbar). Der Entrypoint startet als
# root, macht /data für "app" beschreibbar und wechselt dann per setpriv zu "app".
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} app && useradd -u ${UID} -g ${GID} -M app \
    && mkdir -p /data && chown app:app /data
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

VOLUME ["/data"]
EXPOSE 8000

WORKDIR /srv/backend
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
