"""Runtime settings from environment variables (all optional; defaults run Replay-only)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def youcam_key() -> str:
    """Key for Live mode: env YOUCAM_API_KEY (production: injected by `infisical run`).
    Local convenience on macOS: Keychain item `youcam-api-key-lookbrief`, read only when LOOKBRIEF_KEYCHAIN=1."""
    key = os.environ.get("YOUCAM_API_KEY", "").strip()
    if not key and os.environ.get("LOOKBRIEF_KEYCHAIN") == "1":
        try:
            key = subprocess.run(["security", "find-generic-password", "-s", "youcam-api-key-lookbrief", "-w"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            key = ""
    return key


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("LOOKBRIEF_DATA", ROOT / "data")))
    samples_dir: Path = field(default_factory=lambda: Path(os.environ.get("LOOKBRIEF_SAMPLES", ROOT / "samples")))
    public_url: str = field(default_factory=lambda: os.environ.get("LOOKBRIEF_PUBLIC_URL", "").rstrip("/"))
    live_enabled: bool = field(default_factory=lambda: os.environ.get("LOOKBRIEF_LIVE", "1") == "1")
    live_unit_budget: int = field(default_factory=lambda: _int("LOOKBRIEF_LIVE_UNIT_BUDGET", 200))
    live_min_credit: int = field(default_factory=lambda: _int("LOOKBRIEF_LIVE_MIN_CREDIT", 100))
    live_sessions_per_ip_day: int = field(default_factory=lambda: _int("LOOKBRIEF_LIVE_SESSIONS_PER_IP_DAY", 5))
    live_session_unit_cap: int = field(default_factory=lambda: _int("LOOKBRIEF_LIVE_SESSION_UNIT_CAP", 12))
    trust_proxy: bool = field(default_factory=lambda: os.environ.get("LOOKBRIEF_TRUST_PROXY", "0") == "1")
    upload_ttl_hours: int = field(default_factory=lambda: _int("LOOKBRIEF_UPLOAD_TTL_HOURS", 24))
    replay_ttl_hours: int = field(default_factory=lambda: _int("LOOKBRIEF_REPLAY_TTL_HOURS", 24 * 30))
    max_replay_sessions: int = field(default_factory=lambda: _int("LOOKBRIEF_MAX_REPLAY_SESSIONS", 400))
    try_per_ip_day: int = field(default_factory=lambda: _int("LOOKBRIEF_TRY_PER_IP_DAY", 60))
    max_upload_mb: int = field(default_factory=lambda: _int("LOOKBRIEF_MAX_UPLOAD_MB", 12))
    cleanup_every_s: int = field(default_factory=lambda: _int("LOOKBRIEF_CLEANUP_EVERY_S", 1800))
    attest_key_b64: str = field(default_factory=lambda: os.environ.get("LOOKBRIEF_ATTEST_KEY", ""))
    attest_ephemeral: bool = field(default_factory=lambda: os.environ.get("LOOKBRIEF_ATTEST_EPHEMERAL", "0") == "1")
