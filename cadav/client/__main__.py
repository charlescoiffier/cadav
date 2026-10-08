import argparse
from pathlib import Path

from cadav.client.app import CadavApp
from cadav.client.theme import PALETTES


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cadav play", description="cadav : cadavre exquis en terminal")
    parser.add_argument("--url", help="adresse du serveur, ex. ws://localhost:8765")
    parser.add_argument("--theme", choices=sorted(PALETTES), help="palette de couleurs (défaut : galaxy)")
    parser.add_argument("--config", type=Path, help="fichier de configuration locale")
    args = parser.parse_args(argv)
    CadavApp(config_path=args.config, url=args.url, theme=args.theme).run()


if __name__ == "__main__":
    main()
