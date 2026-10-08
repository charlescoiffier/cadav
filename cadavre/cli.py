"""Command line entry point: ``cadavre serve`` and ``cadavre play``."""

from __future__ import annotations

import sys

USAGE = """usage: cadavre {serve,play} [options]

  serve   lance le serveur (cadavre serve --help)
  play    lance le client  (cadavre play --help)
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command, rest = (args[0], args[1:]) if args else ("", [])
    if command == "serve":
        from cadavre.server import main as serve

        serve(rest)
    elif command == "play":
        from cadavre.client.__main__ import main as play

        play(rest)
    else:
        print(USAGE, file=sys.stderr if command else sys.stdout)
        return 2 if command else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
