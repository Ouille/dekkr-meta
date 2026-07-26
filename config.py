"""Configuration persistante de dekkr-meta.

La configuration vit dans %APPDATA%\\dekkr-meta\\config.json. Les modules
consommateurs importent l'objet `cfg` et lisent ses attributs *à l'appel*,
jamais à l'import : les réglages sont modifiables à chaud depuis la fenêtre
Paramètres.
"""

import json
import os
import sys
import winreg
from dataclasses import dataclass, asdict, field

APP_NAME = "dekkr-meta"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DUMP_INDEX = "https://data.discogs.com/?prefix=data%2F2026%2F"


def _appdata_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


CONFIG_PATH = os.path.join(_appdata_dir(), "config.json")


def _exe_path() -> str:
    """Chemin de l'exécutable, que l'on tourne gelé (PyInstaller) ou non."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def _app_dir() -> str:
    """Dossier de l'application (à côté de l'exe, ou du code en dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _default_db_path() -> str:
    """Emplacement de la base au tout premier lancement.

    On adopte une base déjà présente plutôt que d'en réclamer une nouvelle :
    un import coûte une heure et 10 Go de téléchargement. Le dossier parent
    est inspecté car l'exécutable gelé vit dans `dist/`, un cran sous le
    dossier de travail où la base a pu être construite.
    """
    app = _app_dir()
    candidates = [
        os.path.join(app, "discogs.db"),
        os.path.join(os.path.dirname(app), "discogs.db"),
        os.path.join(os.getcwd(), "discogs.db"),
        os.path.join(_appdata_dir(), "discogs.db"),
    ]
    for path in candidates:
        try:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        except OSError:
            continue
    return os.path.join(_appdata_dir(), "discogs.db")


@dataclass
class Config:
    port: int = 7433
    match_threshold: int = 85
    discogs_token: str = ""
    db_path: str = field(default_factory=_default_db_path)
    index_tracks: bool = True
    autostart: bool = False

    # -- Dérivés --

    @property
    def db_exists(self) -> bool:
        return os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 0

    @property
    def db_size_gb(self) -> float:
        try:
            return os.path.getsize(self.db_path) / 1024 ** 3
        except OSError:
            return 0.0


def load_config() -> Config:
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}

    known = {f for f in Config.__dataclass_fields__}
    c = Config(**{k: v for k, v in data.items() if k in known})

    # Surcharges d'environnement (confort de développement)
    for env, attr, cast in (
        ("PORT", "port", int),
        ("MATCH_THRESHOLD", "match_threshold", int),
        ("DISCOGS_TOKEN", "discogs_token", str),
        ("DB_PATH", "db_path", str),
    ):
        v = os.environ.get(env)
        if v:
            try:
                setattr(c, attr, cast(v))
            except ValueError:
                pass
    return c


def save_config(c: "Config" = None) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(c or cfg), f, indent=2, ensure_ascii=False)


def needs_setup() -> bool:
    """Vrai tant que la base Discogs n'a pas été importée."""
    return not cfg.db_exists


# -- Démarrage automatique Windows --

def set_autostart(enabled: bool) -> None:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{_exe_path()}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass


def is_autostart_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


cfg: Config = load_config()

# Fige le chemin retenu au premier lancement : sans cela, un exe déplacé
# repartirait sur %APPDATA% et réclamerait un import déjà effectué.
if not os.path.exists(CONFIG_PATH):
    try:
        save_config(cfg)
    except OSError:
        pass
