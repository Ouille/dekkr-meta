"""Import du dump Discogs en ligne de commande, avec progression.

Usage :  python import_cli.py [--slice-mb N]
"""
import argparse
import threading
import time

from importer import resolve_latest_dump, import_dump, get_progress
from database import set_meta
from config import INDEX_TRACKS


def _monitor(stop: threading.Event):
    t0 = time.time()
    while not stop.wait(30):
        p = get_progress()
        mn = (time.time() - t0) / 60
        mb = p["mb_read"]
        rate = mb / mn if mn else 0
        print(
            f"[{mn:6.1f} min] {mb:8.0f} Mo lus  "
            f"({rate:5.1f} Mo/min)  "
            f"{p['releases']:>10,} sorties  {p['entries']:>11,} entrees",
            flush=True,
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice-mb", type=int, default=None,
                    help="limiter la lecture (test)")
    args = ap.parse_args()

    url, date = resolve_latest_dump()
    print(f"Dump          : {date}")
    print(f"Tracklists    : {'indexees' if INDEX_TRACKS else 'ignorees'}")
    print(f"Tranche       : {args.slice_mb or 'complet'}\n", flush=True)

    stop = threading.Event()
    threading.Thread(target=_monitor, args=(stop,), daemon=True).start()

    t0 = time.time()
    res = import_dump(
        url,
        max_bytes=args.slice_mb * 1024 * 1024 if args.slice_mb else None,
        index_tracks=INDEX_TRACKS,
    )
    stop.set()

    if not args.slice_mb:
        set_meta("dump_date", date)
        set_meta("index_tracks", "1" if INDEX_TRACKS else "0")

    print("\n=== Import termine ===")
    for k, v in res.items():
        print(f"  {k:16} {v}")
    print(f"  duree totale     {(time.time() - t0)/60:.1f} min")


if __name__ == "__main__":
    main()
