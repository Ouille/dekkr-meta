"""Icône de barre des tâches de dekkr-meta."""

import pystray
from PIL import Image, ImageDraw

APP_NAME = "dekkr-meta"

_COLORS = {
    "ready":     (34, 197, 94),    # vert  — base prête
    "importing": (250, 204, 21),   # jaune — import en cours
    "no_db":     (249, 115, 22),   # orange— base absente
    "error":     (239, 68, 68),    # rouge
}


def _make_icon(color: tuple, ring: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=(*color, 255))
    if ring:
        # Anneau interne : signale que la base n'est pas exploitable.
        draw.ellipse([22, 22, 42, 42], fill=(0, 0, 0, 0))
    return img


class TrayIcon:
    def __init__(self, cfg, on_open_status, on_open_settings, on_import, on_quit):
        self._cfg = cfg
        self._on_open_status = on_open_status
        self._on_open_settings = on_open_settings
        self._on_import = on_import
        self._on_quit = on_quit
        self._state = "no_db"
        self._detail = ""
        self._icon: pystray.Icon | None = None

    # -- Menu --

    def _status_label(self) -> str:
        return {
            "ready": f"Base prête — port {self._cfg.port}",
            "importing": f"Import en cours — {self._detail}",
            "no_db": "Base Discogs absente",
            "error": f"Erreur — {self._detail}",
        }.get(self._state, APP_NAME)

    def _build_menu(self) -> pystray.Menu:
        from config import is_autostart_enabled, set_autostart, save_config

        def toggle_autostart(icon, item):
            new_val = not is_autostart_enabled()
            set_autostart(new_val)
            self._cfg.autostart = new_val
            save_config(self._cfg)
            self._refresh_menu()

        importing = self._state == "importing"
        import_label = (
            "Import en cours…" if importing
            else ("Mettre à jour la base Discogs" if self._state == "ready"
                  else "Importer la base Discogs (~1 h, 20 Go)")
        )

        return pystray.Menu(
            pystray.MenuItem(self._status_label(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ouvrir la fenêtre de statut", lambda i, it: self._on_open_status()),
            pystray.MenuItem(import_label, lambda i, it: self._on_import(), enabled=not importing),
            pystray.MenuItem("Paramètres", lambda i, it: self._on_open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Démarrer au démarrage Windows",
                toggle_autostart,
                checked=lambda item: is_autostart_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda i, it: self._do_quit()),
        )

    def _refresh_menu(self) -> None:
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    # -- État --

    def set_state(self, state: str, detail: str = "") -> None:
        if state == self._state and detail == self._detail:
            return
        self._state = state
        self._detail = detail
        if self._icon:
            self._icon.icon = _make_icon(
                _COLORS.get(state, _COLORS["no_db"]),
                ring=state in ("no_db", "error"),
            )
            self._icon.title = f"{APP_NAME} — {self._status_label()}"
            self._refresh_menu()

    def notify(self, msg: str) -> None:
        if self._icon:
            try:
                self._icon.notify(msg, APP_NAME)
            except Exception:
                pass

    def _do_quit(self) -> None:
        if self._icon:
            self._icon.stop()
        self._on_quit()

    def run(self) -> None:
        self._icon = pystray.Icon(
            APP_NAME,
            icon=_make_icon(_COLORS[self._state], ring=True),
            title=APP_NAME,
            menu=self._build_menu(),
        )
        self._icon.run()
