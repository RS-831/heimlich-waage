"""Nutzer-Ermittlung. Ohne Web-Framework, damit sie für sich getestet werden kann.

AUTH_MODE=none:  immer der Standardnutzer (lokaler Betrieb).
AUTH_MODE=proxy: Ein vorgeschalteter Anmeldedienst (z. B. Traefik + Authelia) setzt Header mit
                 Login-Name, Anzeigename und Gruppen. Die App vertraut diesen Headern. Das ist
                 nur sicher, wenn der Port ausschließlich für den Proxy erreichbar ist!
"""
from __future__ import annotations

import ipaddress
from typing import Mapping

from app.core.config import Settings
from app.core.models import User
from app.storage.repository import Repository


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _header(headers: Mapping[str, str], name: str) -> str:
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return (value or "").strip()
    return ""


def _trusted(client_host: str | None, s: Settings) -> bool:
    if not s.auth_trusted_proxies:
        return True
    try:
        ip = ipaddress.ip_address(client_host or "")
    except ValueError:
        return False
    return any(ip in net for net in s.auth_trusted_proxies)


def resolve_user(repo: Repository, s: Settings, headers: Mapping[str, str],
                 client_host: str | None) -> User:
    if s.auth_mode == "none":
        return repo.default_user()

    if not _trusted(client_host, s):
        raise AuthError(401, "Anfrage nicht über den Proxy")
    username = _header(headers, s.auth_user_header).lower()
    if not username:
        raise AuthError(401, "Nicht angemeldet")
    groups = {g.strip() for g in _header(headers, s.auth_groups_header).split(",") if g.strip()}
    if s.auth_required_group and s.auth_required_group not in groups:
        raise AuthError(403, "Kein Zugriff auf die Waage")
    role = "admin" if s.auth_admin_group and s.auth_admin_group in groups else "user"

    user = repo.get_user_by_username(username)
    if user is None and s.auth_adopt_default_user and username == s.auth_adopt_default_user:
        user = repo.adopt_default_user(username)
    if user is None:
        name = _header(headers, s.auth_name_header) or username
        user = repo.create_user(username, name, role)
    return repo.touch_user(user.id, role)
