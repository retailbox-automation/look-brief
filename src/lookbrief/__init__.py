"""Look Brief."""

from pathlib import Path

__version__ = "0.1.0"


def build_id() -> str:
    """Commit the running image was built from (written into BUILD by scripts/export_for_deploy.sh)."""
    p = Path(__file__).with_name("BUILD")
    return p.read_text().strip() if p.exists() else "dev"
