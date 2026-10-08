import argparse
from pathlib import Path

from cadavre.client.app import CadavreApp


def main() -> None:
    parser = argparse.ArgumentParser(description="Cadavre exquis en terminal")
    parser.add_argument("--url", help="adresse du serveur, ex. ws://localhost:8765")
    parser.add_argument("--config", type=Path, help="fichier de configuration locale")
    args = parser.parse_args()
    CadavreApp(config_path=args.config, url=args.url).run()


if __name__ == "__main__":
    main()
