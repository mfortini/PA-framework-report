from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from common import ROOT, elapsed_str, ensure_directories, log_step


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Esegue la pipeline completa")
    parser.add_argument(
        "--steps",
        nargs="*",
        default=[
            "01_prepare_input.py",
            "02_probe_homepages.py",
            "03_collect_js_inventory.py",
            "04_download_js.py",
            "05_detect_frameworks.py",
            "06_build_reports.py",
            "07_build_web_report.py",
        ],
        help="Lista degli script da eseguire in ordine",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_directories()
    scripts_dir = ROOT / "scripts"
    t_pipeline = time.monotonic()
    log_step(f"Pipeline start: {len(args.steps)} steps")
    for i, step in enumerate(args.steps, start=1):
        script_path = scripts_dir / step
        log_step(f"[{i}/{len(args.steps)}] Starting {script_path.name}")
        t_step = time.monotonic()
        result = subprocess.run([sys.executable, str(script_path)], check=False)
        step_elapsed = elapsed_str(time.monotonic() - t_step)
        if result.returncode != 0:
            log_step(f"[{i}/{len(args.steps)}] FAILED {script_path.name} (exit {result.returncode}) elapsed={step_elapsed}")
            return result.returncode
        log_step(f"[{i}/{len(args.steps)}] Done {script_path.name} elapsed={step_elapsed}")
    total_elapsed = elapsed_str(time.monotonic() - t_pipeline)
    log_step(f"Pipeline completed: {len(args.steps)} steps elapsed={total_elapsed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
