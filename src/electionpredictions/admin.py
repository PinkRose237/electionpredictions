"""Admin page configuration: a PBKDF2 password hash the static site can verify in the browser.

The hash lives in site/admin-config.json (public) and, for the archived 2026 corrections desk, in
site/archive/2026/admin-config.json. It only gates the admin UI (including the archived 2026 midterm pages);
publishing corrections requires the admin's own GitHub token, which never leaves their browser.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess

from .config import ARCHIVE_2026_DIR, SITE_DIR

CONFIG_PATH = SITE_DIR / "admin-config.json"
ARCHIVE_CONFIG_PATH = ARCHIVE_2026_DIR / "admin-config.json"
CONFIG_PATHS = (CONFIG_PATH, ARCHIVE_CONFIG_PATH)
RESULTS_PATH = "site/archive/2026/data/results.json"
ITERATIONS = 200_000


def pbkdf2_hex(password: str, salt_hex: str, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations, dklen=32).hex()


def detect_repo() -> str | None:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    url = url.removesuffix(".git")
    if "github.com" in url:
        return url.split("github.com")[-1].lstrip(":/")
    return None


def write_config(password: str, repo: str | None = None, branch: str = "main", path: str = RESULTS_PATH) -> dict:
    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            existing = {}
    salt = secrets.token_hex(16)
    cfg = dict(
        salt=salt, hash=pbkdf2_hex(password, salt), iterations=ITERATIONS,
        repo=repo or existing.get("repo") or detect_repo() or "",
        branch=branch or existing.get("branch", "main"), path=path or existing.get("path", RESULTS_PATH),
    )
    for p in (CONFIG_PATH, ARCHIVE_CONFIG_PATH):  # read at call time (tests patch them)
        if p.parent.exists():
            p.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg
