"""Mint a local HS256 bearer token for development."""

import argparse

from src.core.config import get_settings
from src.core.security import create_access_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a DeepTune dev bearer token.")
    parser.add_argument(
        "--subject",
        default="local-dev",
        help="Token subject (recorded in the `sub` claim).",
    )
    args = parser.parse_args()
    settings = get_settings()
    print(create_access_token(args.subject, settings))


if __name__ == "__main__":
    main()
