#!/usr/bin/env bash
# heimlich · Waage – lokale Instanz verwalten.
#
#   ./waage.sh            startet die App (wie ./waage.sh start)
#   ./waage.sh start      bauen und starten, danach Adresse anzeigen
#   ./waage.sh stop       anhalten (Daten bleiben erhalten)
#   ./waage.sh restart    neu starten
#   ./waage.sh status     läuft sie? Erreichbar?
#   ./waage.sh logs       Protokoll live ansehen (Strg+C beendet nur die Anzeige)
#   ./waage.sh update     neuesten Stand von GitHub holen und neu starten
#   ./waage.sh backup     Datenbank als Kopie in den Datenordner sichern
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B= G= Y= R= N=; fi
info() { printf '%s==>%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '%s✔%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '%s✘ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

env_value() {  # Wert aus .env lesen, sonst Standard
  local v
  v=$(grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)
  printf '%s' "${v:-$2}"
}

checks() {
  [ "$(id -u)" -ne 0 ] || die "Bitte nicht als root bzw. mit sudo starten, sondern als normaler Benutzer."
  command -v docker >/dev/null || die "Docker ist nicht installiert."
  docker info >/dev/null 2>&1 || die "Kein Zugriff auf Docker. Ist der Dienst gestartet und dein Benutzer in der Gruppe 'docker'?
  sudo usermod -aG docker \$USER   (danach ab- und wieder anmelden)"
  docker compose version >/dev/null 2>&1 || die "'docker compose' fehlt (Paket docker-compose-plugin)."
}

ensure_env() {
  if [ ! -f .env ]; then
    info "Lege .env an (einmalig)"
    sed -e "s|^DATA_PATH=.*|DATA_PATH=$HOME/gewicht-daten|" \
        -e "s|^UID=.*|UID=$(id -u)|" -e "s|^GID=.*|GID=$(id -g)|" .env.example > .env
    ok ".env erstellt (Datenordner: $HOME/gewicht-daten)"
  fi
  local data
  data=$(env_value DATA_PATH "$HOME/gewicht-daten")
  data=${data/#\~/$HOME}
  if [ ! -d "$data" ]; then
    mkdir -p "$data" && ok "Datenordner angelegt: $data"
  fi
  [ -w "$data" ] || die "Datenordner $data ist für dich nicht beschreibbar. Lösung: sudo chown -R $(id -un): \"$data\""
}

port() { env_value PORT 8000; }

http_ok() {  # curl, wget oder python3 – was eben da ist
  if command -v curl >/dev/null; then curl -fsS "$1" >/dev/null 2>&1
  elif command -v wget >/dev/null; then wget -qO /dev/null "$1"
  else python3 -c "import sys,urllib.request;urllib.request.urlopen(sys.argv[1],timeout=3)" "$1" >/dev/null 2>&1
  fi
}

wait_healthy() {
  local url="http://localhost:$(port)/api/health"
  for _ in $(seq 1 30); do
    if http_ok "$url"; then return 0; fi
    sleep 1
  done
  return 1
}

show_urls() {
  local p ip
  p=$(port)
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  printf '  Am Laptop:   %shttp://localhost:%s%s\n' "$B" "$p" "$N"
  [ -n "$ip" ] && printf '  Vom Handy:   %shttp://%s:%s%s   (im selben WLAN)\n' "$B" "$ip" "$p" "$N"
  echo
}

cmd_start() {
  checks; ensure_env
  info "Baue und starte heimlich · Waage …"
  docker compose up -d --build
  info "Warte, bis die App antwortet …"
  if wait_healthy; then
    ok "Läuft."
    show_urls
  else
    warn "Die App antwortet noch nicht. Letzte Protokollzeilen:"
    docker compose logs --tail 20
    exit 1
  fi
}

cmd_stop()    { checks; info "Halte an …"; docker compose down; ok "Angehalten. Deine Daten bleiben erhalten."; }
cmd_restart() { cmd_stop; cmd_start; }
cmd_logs()    { checks; docker compose logs -f --tail 50; }

cmd_status() {
  checks
  docker compose ps
  if http_ok "http://localhost:$(port)/api/health"; then
    ok "Erreichbar."; show_urls
  else
    warn "Nicht erreichbar. Starten mit: ./waage.sh start"
  fi
}

cmd_update() {
  checks
  info "Hole neuesten Stand von GitHub …"
  git pull --ff-only || die "git pull fehlgeschlagen. Hast du lokale Änderungen? (git status)"
  cmd_start
}

cmd_backup() {
  ensure_env
  local data db stamp
  data=$(env_value DATA_PATH "$HOME/gewicht-daten"); data=${data/#\~/$HOME}
  db=$(env_value DB_FILE gewicht.db)
  [ -f "$data/$db" ] || die "Keine Datenbank gefunden unter $data/$db"
  mkdir -p "$data/backups"
  stamp=$(date +%Y-%m-%d_%H%M%S)
  # Konsistente Kopie auch bei laufender App (SQLite-Online-Backup)
  if command -v sqlite3 >/dev/null; then
    sqlite3 "$data/$db" ".backup '$data/backups/${db%.db}-$stamp.db'"
  else
    docker compose exec -T heimlich-waage python -c \
      "import sqlite3;s=sqlite3.connect('/data/$db');d=sqlite3.connect('/data/backups/${db%.db}-$stamp.db');s.backup(d)" \
      || die "Für ein Backup braucht es 'sqlite3' (sudo apt install sqlite3) oder eine laufende App (./waage.sh start)."
  fi
  ok "Gesichert: $data/backups/${db%.db}-$stamp.db"
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  logs)    cmd_logs ;;
  update)  cmd_update ;;
  backup)  cmd_backup ;;
  -h|--help|help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "Unbekannter Befehl: $1   (Hilfe: ./waage.sh help)" ;;
esac
