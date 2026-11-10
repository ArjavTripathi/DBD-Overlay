"""Command-line entry point.

    dbd-overlay                 run the app (same as `dbd-overlay run`)
    dbd-overlay ctl <command>   send a command to the running app (for Hyprland binds)
    dbd-overlay ctl --list      list commands
    dbd-overlay replay <dir>    run detection on saved screenshots
    dbd-overlay export <file>   match history to .json / .csv (import <file.json> to restore)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import paths
from .core.commands import COMMANDS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dbd-overlay", description="DBD map overlay + winstreak HUD")
    sub = ap.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="run the app (default)")
    run.add_argument("--config", type=Path, default=paths.config_file())
    run.add_argument("--debug", action="store_true", help="verbose logging")

    ctl = sub.add_parser("ctl", help="send a command to the running app")
    ctl.add_argument("command", nargs="?", choices=sorted(COMMANDS), metavar="command")
    ctl.add_argument("arg", nargs="*", help="argument, e.g. a map name for set-map")
    ctl.add_argument("--list", action="store_true", help="list available commands")

    rp = sub.add_parser("replay", help="run detection on saved screenshots (no game needed)")
    rp.add_argument("paths", nargs="+", type=Path, help="image files and/or directories")
    rp.add_argument("--manifest", type=Path, help="JSON of expected results; exit 1 on mismatch")
    rp.add_argument("--interval", type=float, default=1.0, help="assumed seconds between frames")
    rp.add_argument("-v", "--verbose", action="store_true", help="also list frames without a title card")

    ex = sub.add_parser("export", help="export match history (.json or .csv)")
    ex.add_argument("path", type=Path)
    im = sub.add_parser("import", help="import matches from a .json export (duplicates skipped)")
    im.add_argument("path", type=Path)

    args = ap.parse_args(argv)

    if args.cmd == "ctl":
        return _ctl(args)
    if args.cmd in ("export", "import"):
        from .storage import export as ex_mod
        from .storage.db import Database

        db = Database(paths.db_file())  # safe while the app runs: SQLite handles both
        if args.cmd == "export":
            print(f"exported {ex_mod.export(db, args.path)} matches to {args.path}")
        else:
            added, skipped = ex_mod.import_json(db, args.path)
            print(f"imported {added} matches ({skipped} already present); restart the app to refresh the HUD")
        return 0
    if args.cmd == "replay":
        from .detection import replay

        return replay.run(args.paths, args.manifest, args.verbose, args.interval)

    # Imported lazily so `ctl` (called on every hotkey press) stays fast.
    from .app import App
    from .core.config import ConfigError

    try:
        app = App(getattr(args, "config", paths.config_file()), getattr(args, "debug", False))
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    return app.run()


def _ctl(args: argparse.Namespace) -> int:
    if args.list or not args.command:
        for name, help_ in COMMANDS.items():
            print(f"  {name:<16} {help_}")
        return 0
    from .ipc import send_command

    reply = send_command(" ".join([args.command, *args.arg]), paths.control_socket_name())
    if reply is None:
        print("dbd-overlay is not running", file=sys.stderr)
        return 1
    print(reply)
    return 0 if reply.startswith("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
