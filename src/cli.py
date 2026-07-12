from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import get_settings
from src.dependencies import get_service
from src.logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administration du data lake VelibPulse")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Creer le bucket, les schemas et les tables")

    reference = subparsers.add_parser("reference", help="Ingerer le dataset CSV de reference")
    reference.add_argument("--path", type=Path, default=None)

    subparsers.add_parser("api", help="Ingerer et traiter un instantane de l'API Velib'")
    subparsers.add_parser("run", help="Executer le pipeline complet fichier + API")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    service = get_service()

    if args.command == "init":
        service.initialize()
        result = {"status": "initialized"}
    elif args.command == "reference":
        result = service.load_reference_file(args.path)
    elif args.command == "api":
        result = service.run_api_pipeline()
    else:
        service.initialize()
        result = {
            "reference": service.load_reference_file(),
            "api": service.run_api_pipeline(),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

