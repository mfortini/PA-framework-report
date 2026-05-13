from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
JS_FILES_DIR = RESULTS_DIR / "js_files"
HOMEPAGES_HTML_DIR = RESULTS_DIR / "homepages_html"
LOGS_DIR = ROOT / "logs"


def ensure_directories() -> None:
    for path in (DATA_DIR, RESULTS_DIR, JS_FILES_DIR, HOMEPAGES_HTML_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def log_step(message: str) -> None:
    print(f"[{now_iso()}] {message}", flush=True)


def log_progress(step: str, current: int, total: int, extra: str = "") -> None:
    suffix = f" | {extra}" if extra else ""
    print(f"[{now_iso()}] {step}: {current}/{total}{suffix}", flush=True)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def iter_jsonl(path: Path) -> Iterator[dict[str, object]]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, records: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
        handle.flush()


def load_processed_values(path: Path, key: str) -> set[str]:
    processed: set[str] = set()
    if not path.exists():
        return processed
    for record in iter_jsonl(path):
        value = record.get(key)
        if value:
            processed.add(str(value))
    return processed


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def resolve_obscura_binary(cli_value: str | None = None) -> str | None:
    candidates = [
        cli_value,
        os.environ.get("OBSCURA_BIN"),
        str(ROOT / "obscura"),
        shutil.which("obscura"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate).resolve())
    return None


def build_obscura_env(obscura_bin: str) -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = str(Path(obscura_bin).resolve().parent)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return env


def allocate_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def html_snapshot_path(homepage_url: str) -> Path:
    parsed = urlparse(homepage_url)
    host = slugify(parsed.netloc or "site")
    digest = sha256_text(homepage_url)[:12]
    return HOMEPAGES_HTML_DIR / f"{host}-{digest}.html"


def maybe_limit_rows(rows: list, limit: int | None) -> list:
    if limit is None or limit <= 0:
        return rows
    return rows[:limit]


@contextmanager
def obscura_service(
    obscura_bin: str,
    port: int,
    workers: int = 1,
    stealth: bool = False,
    verbose: bool = False,
) -> Iterator[subprocess.Popen[str]]:
    cmd = [obscura_bin, "serve", "--port", str(port), "--workers", str(workers)]
    if stealth:
        cmd.append("--stealth")
    if verbose:
        cmd.insert(1, "--verbose")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=build_obscura_env(obscura_bin),
    )
    try:
        wait_for_obscura_ready(port, process)
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_for_obscura_ready(port: int, process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        if process.poll() is not None:
            stdout = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"obscura serve exited early with {process.returncode}: {stdout}")
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for Obscura on {url}")


def normalize_url(raw_url: str) -> tuple[str | None, str | None]:
    value = (raw_url or "").strip()
    if not value:
        return None, "missing_sito_istituzionale"
    value = value.replace(" ", "")
    if value.startswith("//"):
        value = f"https:{value}"
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None, "unsupported_scheme"
    if not parsed.netloc:
        return None, "missing_hostname"
    hostname = parsed.netloc.lower()
    if "." not in hostname:
        return None, "invalid_hostname"
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=hostname,
        fragment="",
    )
    cleaned = urlunparse(normalized)
    return cleaned.rstrip("/"), None


def elapsed_str(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def rate_str(elapsed_s: float, done: int, unit: str = "it") -> str:
    if elapsed_s <= 0 or done <= 0:
        return ""
    return f"{done / elapsed_s:.1f} {unit}/s"


def eta_str(elapsed_s: float, done: int, total: int) -> str:
    remaining = total - done
    if remaining <= 0 or elapsed_s <= 0 or done <= 0:
        return ""
    s = remaining * elapsed_s / done
    if s < 60:
        return f"ETA ~{s:.0f}s"
    if s < 3600:
        return f"ETA ~{int(s / 60)}m"
    return f"ETA ~{s / 3600:.1f}h"


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered.strip("-") or "item"
