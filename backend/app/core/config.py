"""Zentrale Konfiguration. Alle Werte kommen aus Umgebungsvariablen."""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path

AUTH_MODES = ("none", "proxy")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _networks(text: str) -> tuple:
    nets = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise SystemExit(f"AUTH_TRUSTED_PROXIES: ungültige Adresse {part!r}") from None
    return tuple(nets)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/data")))
    db_file: str = field(default_factory=lambda: _env("DB_FILE", "gewicht.db"))

    # none  = lokaler Betrieb, immer der Standardnutzer
    # proxy = Nutzer kommt aus Headern eines vorgeschalteten Anmeldedienstes (z. B. Authelia)
    auth_mode: str = field(default_factory=lambda: _env("AUTH_MODE", "none").lower())
    auth_user_header: str = field(default_factory=lambda: _env("AUTH_USER_HEADER", "Remote-User"))
    auth_name_header: str = field(default_factory=lambda: _env("AUTH_NAME_HEADER", "Remote-Name"))
    auth_groups_header: str = field(default_factory=lambda: _env("AUTH_GROUPS_HEADER", "Remote-Groups"))
    auth_admin_group: str = field(default_factory=lambda: _env("AUTH_ADMIN_GROUP", "admins"))
    auth_required_group: str = field(default_factory=lambda: _env("AUTH_REQUIRED_GROUP"))
    auth_adopt_default_user: str = field(default_factory=lambda: _env("AUTH_ADOPT_DEFAULT_USER").lower())
    auth_logout_url: str = field(default_factory=lambda: _env("AUTH_LOGOUT_URL"))
    auth_trusted_proxies: tuple = field(default_factory=lambda: _networks(_env("AUTH_TRUSTED_PROXIES")))

    def __post_init__(self) -> None:
        if self.auth_mode not in AUTH_MODES:
            raise SystemExit(
                f"AUTH_MODE={self.auth_mode!r} ist ungültig. Erlaubt: {', '.join(AUTH_MODES)}. "
                "Für den Betrieb hinter Authelia/einem Anmelde-Proxy: AUTH_MODE=proxy."
            )

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_file


settings = Settings()
