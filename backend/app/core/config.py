"""Zentrale Konfiguration. Alle Werte kommen aus Umgebungsvariablen."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("DATA_DIR", "/data"))
    db_file: str = os.environ.get("DB_FILE", "gewicht.db")
    auth_mode: str = os.environ.get("AUTH_MODE", "none")  # none | local (spaeter NAS)

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_file


settings = Settings()
