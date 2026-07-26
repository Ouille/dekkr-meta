"""Fenêtres tkinter de dekkr-meta.

Un seul tk.Tk() caché tourne sur un thread dédié ; toutes les fenêtres sont
des Toplevel postées via une file. pystray appelle depuis son propre thread
Win32 — ouvrir tkinter directement depuis ces callbacks plante en silence.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from config import cfg, save_config

APP_TITLE = "dekkr-meta"
BG = "#1a1a1a"
FG = "#e0e0e0"
MUTED = "#8a8a8a"
ACCENT = "#22c55e"
BTN_BG = "#2a2a2a"

_tk_queue: "queue.Queue" = queue.Queue()
_tk_root: tk.Tk | None = None


def _tk_worker() -> None:
    global _tk_root
    _tk_root = tk.Tk()
    _tk_root.withdraw()

    def _pump():
        try:
            while True:
                fn = _tk_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        _tk_root.after(100, _pump)

    _tk_root.after(100, _pump)
    _tk_root.mainloop()


def start_tk_thread() -> None:
    threading.Thread(target=_tk_worker, daemon=True).start()


def _post(fn) -> None:
    _tk_queue.put(fn)


# -- Fabriques de widgets --

def _window(title: str, w: int, h: int) -> tk.Toplevel:
    win = tk.Toplevel(_tk_root)
    win.title(title)
    win.configure(bg=BG)
    win.geometry(f"{w}x{h}")
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))
    return win


def _label(parent, text, fg=FG, size=10, bold=False, **kw):
    return tk.Label(
        parent, text=text, bg=BG, fg=fg,
        font=("Segoe UI", size, "bold" if bold else "normal"),
        justify="left", anchor="w", **kw,
    )


def _button(parent, text, cmd, accent=False):
    return tk.Button(
        parent, text=text, command=cmd,
        bg=ACCENT if accent else BTN_BG,
        fg="#000000" if accent else FG,
        activebackground=ACCENT if accent else "#3a3a3a",
        relief="flat", font=("Segoe UI", 10), padx=14, pady=6, cursor="hand2",
    )


# -- Fenêtre de statut --

def open_status_window(get_status) -> None:
    def build():
        win = _window(f"{APP_TITLE} — statut", 460, 300)
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        _label(body, APP_TITLE, size=14, bold=True).pack(anchor="w")
        state_lbl = _label(body, "", fg=MUTED)
        state_lbl.pack(anchor="w", pady=(2, 12))

        bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        rows = {}
        for key in ("Base", "Sorties", "Entrées", "Dump", "Pochettes"):
            fr = tk.Frame(body, bg=BG)
            fr.pack(fill="x", pady=1)
            _label(fr, f"{key}", fg=MUTED, width=12).pack(side="left")
            v = _label(fr, "—")
            v.pack(side="left")
            rows[key] = v

        def refresh():
            if not win.winfo_exists():
                return
            s = get_status()
            imp = s["import"]

            if imp["running"]:
                state_lbl.config(text=f"{imp['step']}  ({imp['mb_read']:.0f} Mo lus)")
                if not bar.winfo_ismapped():
                    bar.pack(fill="x", pady=(6, 10))
                total = 10800.0
                bar["value"] = min(100, 100 * imp["mb_read"] / total)
                rows["Sorties"].config(text=f"{imp['releases']:,}".replace(",", " "))
                rows["Entrées"].config(text=f"{imp['entries']:,}".replace(",", " "))
            else:
                if bar.winfo_ismapped():
                    bar.pack_forget()
                if imp["error"]:
                    state_lbl.config(text=f"Erreur : {imp['error']}", fg="#ef4444")
                elif s["db_ready"]:
                    state_lbl.config(text=f"Base prête — port {cfg.port}", fg=ACCENT)
                else:
                    state_lbl.config(text="Base absente — lancer l'import", fg="#f97316")
                rows["Sorties"].config(text=f"{s['releases_count']:,}".replace(",", " "))
                rows["Entrées"].config(text=f"{s['entries_count']:,}".replace(",", " "))

            rows["Base"].config(text=f"{s['db_size_gb']:.1f} Go" if s["db_size_gb"] else "absente")
            rows["Dump"].config(text=s["dump_date"] or "—")
            rows["Pochettes"].config(
                text="activées" if s["discogs_token"] else "jeton Discogs absent"
            )
            win.after(1000, refresh)

        refresh()
        _button(body, "Fermer", win.destroy).pack(side="bottom", anchor="e", pady=(10, 0))

    _post(build)


# -- Fenêtre paramètres --

def open_settings_window(on_saved=None) -> None:
    def build():
        win = _window(f"{APP_TITLE} — paramètres", 560, 400)
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        _label(body, "Paramètres", size=14, bold=True).pack(anchor="w", pady=(0, 12))

        # Emplacement de la base
        _label(body, "Emplacement de la base Discogs", bold=True).pack(anchor="w")
        _label(body, "Compter ~20 Go. Un disque autre que le disque système convient.",
               fg=MUTED, size=9).pack(anchor="w", pady=(0, 4))
        path_fr = tk.Frame(body, bg=BG)
        path_fr.pack(fill="x", pady=(0, 12))
        path_var = tk.StringVar(value=cfg.db_path)
        path_entry = tk.Entry(path_fr, textvariable=path_var, bg=BTN_BG, fg=FG,
                              relief="flat", font=("Segoe UI", 9), insertbackground=FG)
        path_entry.pack(side="left", fill="x", expand=True, ipady=4)

        def pick_existing():
            f = filedialog.askopenfilename(
                title="Choisir une base Discogs existante",
                filetypes=[("Base SQLite", "*.db"), ("Tous les fichiers", "*.*")],
            )
            if f:
                path_var.set(f)

        def pick_folder():
            d = filedialog.askdirectory(title="Dossier où créer la base Discogs")
            if d:
                path_var.set(os.path.join(d, "discogs.db"))

        _button(path_fr, "Fichier existant…", pick_existing).pack(side="left", padx=(6, 0))
        _button(path_fr, "Nouveau dossier…", pick_folder).pack(side="left", padx=(6, 0))

        # Jeton Discogs
        _label(body, "Jeton Discogs (pochettes)", bold=True).pack(anchor="w")
        _label(body, "Facultatif. Sans jeton, tout fonctionne sauf les pochettes.\n"
                     "À générer sur discogs.com/settings/developers",
               fg=MUTED, size=9).pack(anchor="w", pady=(0, 4))
        token_var = tk.StringVar(value=cfg.discogs_token)
        tk.Entry(body, textvariable=token_var, bg=BTN_BG, fg=FG, relief="flat",
                 font=("Segoe UI", 9), insertbackground=FG).pack(fill="x", ipady=4, pady=(0, 12))

        # Seuil + port
        grid = tk.Frame(body, bg=BG)
        grid.pack(fill="x", pady=(0, 12))

        _label(grid, "Seuil de correspondance", bold=True).grid(row=0, column=0, sticky="w")
        thr_var = tk.IntVar(value=cfg.match_threshold)
        tk.Spinbox(grid, from_=50, to=100, textvariable=thr_var, width=6, bg=BTN_BG,
                   fg=FG, relief="flat", font=("Segoe UI", 9),
                   buttonbackground=BTN_BG).grid(row=0, column=1, sticky="w", padx=(10, 30))

        _label(grid, "Port", bold=True).grid(row=0, column=2, sticky="w")
        port_var = tk.IntVar(value=cfg.port)
        tk.Spinbox(grid, from_=1024, to=65535, textvariable=port_var, width=8, bg=BTN_BG,
                   fg=FG, relief="flat", font=("Segoe UI", 9),
                   buttonbackground=BTN_BG).grid(row=0, column=3, sticky="w", padx=(10, 0))

        _label(body, "Un changement de port ne prend effet qu'au redémarrage.",
               fg=MUTED, size=9).pack(anchor="w")

        # Boutons
        btns = tk.Frame(body, bg=BG)
        btns.pack(side="bottom", fill="x", pady=(14, 0))

        def save():
            new_path = path_var.get().strip()
            if new_path and new_path != cfg.db_path:
                if not os.path.exists(new_path):
                    ok = messagebox.askyesno(
                        APP_TITLE,
                        "Aucune base à cet emplacement.\n\n"
                        "Un nouvel import sera nécessaire (~1 h, 10 Go de "
                        "téléchargement). Confirmer le changement ?",
                        parent=win,
                    )
                    if not ok:
                        return
                cfg.db_path = new_path

            cfg.discogs_token = token_var.get().strip()
            cfg.match_threshold = int(thr_var.get())
            cfg.port = int(port_var.get())
            save_config(cfg)
            if on_saved:
                on_saved()
            win.destroy()

        _button(btns, "Enregistrer", save, accent=True).pack(side="right")
        _button(btns, "Annuler", win.destroy).pack(side="right", padx=(0, 8))

    _post(build)


# -- Confirmation d'import --

def ask_import(parent_title: str, already: bool) -> bool:
    """Boîte de confirmation. Renvoie le choix via un événement synchrone."""
    result: list[bool] = []
    done = threading.Event()

    def build():
        msg = (
            "Mettre à jour la base Discogs ?\n\n"
            if already else
            "Importer la base Discogs ?\n\n"
        ) + (
            "• Téléchargement : environ 10 Go\n"
            "• Durée : environ 1 heure\n"
            "• Espace disque nécessaire : environ 20 Go\n\n"
            "Le service reste utilisable pendant l'import "
            "si une base est déjà en place."
        )
        result.append(bool(messagebox.askyesno(parent_title, msg)))
        done.set()

    _post(build)
    done.wait(timeout=300)
    return result[0] if result else False
