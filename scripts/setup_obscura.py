from __future__ import annotations

import argparse
import tarfile
from pathlib import Path
from urllib.request import urlopen

from common import ROOT

DEFAULT_URL = "https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-x86_64-linux.tar.gz"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scarica Obscura nel workspace")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--archive", type=Path, default=ROOT / "obscura-x86_64-linux.tar.gz")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    obscura_path = ROOT / "obscura"
    worker_path = ROOT / "obscura-worker"
    if obscura_path.exists() and worker_path.exists() and not args.force:
        print(f"Obscura already present at {obscura_path}")
        return 0

    print(f"Downloading {args.url}")
    with urlopen(args.url, timeout=60) as response:  # noqa: S310
        args.archive.write_bytes(response.read())

    with tarfile.open(args.archive, "r:gz") as archive:
        archive.extractall(path=ROOT)

    obscura_path.chmod(0o755)
    worker_path.chmod(0o755)
    print(f"Installed {obscura_path} and {worker_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
