"""dekkr-meta — point d'entrée de l'application.

Architecture (calquée sur dekkr-slsk) :
  - Thread daemon : uvicorn (API HTTP)
  - Thread daemon : surveillance de l'import → état de l'icône
  - Thread dédié  : tkinter (fenêtres statut / paramètres)
  - Thread principal : pystray (bloquant)
"""

import sys
import threading
import time

import uvicorn

import importer
import server as _server
import windows
from config import cfg, save_config, set_autostart, is_autostart_enabled
from database import init_db
from tray import TrayIcon

VERSION = "1.0.0"


def _start_server() -> uvicorn.Server:
    """Lance uvicorn dans un thread daemon.

    `install_signal_handlers` doit être neutralisé : uvicorn ne peut poser de
    gestionnaires de signaux hors du thread principal, occupé par pystray.
    """
    config = uvicorn.Config(
        _server.app, host="127.0.0.1", port=cfg.port,
        log_level="warning", log_config=None,
    )
    srv = uvicorn.Server(config)
    srv.install_signal_handlers = lambda: None
    threading.Thread(target=srv.run, daemon=True).start()
    return srv


def _watch_import(tray: TrayIcon) -> None:
    """Reflète l'état de l'import sur l'icône."""
    while True:
        p = importer.get_progress()
        if p["running"]:
            mb = p["mb_read"]
            pct = min(99, int(100 * mb / 10800)) if mb else 0
            tray.set_state("importing", f"{pct} % ({p['releases']:,} sorties)".replace(",", " "))
        elif p["error"]:
            tray.set_state("error", p["error"][:60])
        elif cfg.db_exists:
            tray.set_state("ready")
        else:
            tray.set_state("no_db")
        time.sleep(1)


def main() -> None:
    init_db()
    windows.start_tk_thread()
    _start_server()

    tray_ref: list[TrayIcon] = []

    def on_import() -> None:
        def worker():
            already = cfg.db_exists
            if not windows.ask_import("dekkr-meta", already):
                return
            tray = tray_ref[0] if tray_ref else None
            if tray:
                tray.notify("Import de la base Discogs démarré.")

            def done(err: str | None) -> None:
                if tray:
                    tray.notify(
                        f"Import échoué : {err}" if err
                        else "Base Discogs prête. dekkr-meta est opérationnel."
                    )

            importer.run_import(on_done=done)

        threading.Thread(target=worker, daemon=True).start()

    tray = TrayIcon(
        cfg,
        on_open_status=lambda: windows.open_status_window(_server.status),
        on_open_settings=lambda: windows.open_settings_window(on_saved=lambda: save_config(cfg)),
        on_import=on_import,
        on_quit=lambda: sys.exit(0),
    )
    tray_ref.append(tray)

    threading.Thread(target=_watch_import, args=(tray,), daemon=True).start()

    # Aligne le réglage sur l'état réel du registre au démarrage.
    cfg.autostart = is_autostart_enabled()

    if not cfg.db_exists:
        tray.notify(
            "Base Discogs absente. Clic droit sur l'icône → "
            "« Importer la base Discogs »."
        )

    tray.run()  # bloquant


if __name__ == "__main__":
    main()
