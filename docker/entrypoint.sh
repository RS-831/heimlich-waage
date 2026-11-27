#!/bin/sh
# Startet als root, sorgt dafür, dass der Nutzer "app" in /data schreiben darf, und gibt die
# Rechte dann ab. Nötig, weil Docker einen fehlenden Bind-Ordner als root anlegt (z. B. auf dem NAS).
set -e

if [ "$(id -u)" = "0" ]; then
  APP_UID=$(id -u app)
  if [ "$(stat -c %u /data)" != "$APP_UID" ]; then
    chown app:app /data
  fi
  # Datenbank-Dateien, die ein anderer Nutzer angelegt hat (z. B. beim Umzug kopiert)
  find /data -maxdepth 1 -type f ! -user app -exec chown app:app {} +
  exec setpriv --reuid=app --regid=app --init-groups -- "$@"
fi

exec "$@"
