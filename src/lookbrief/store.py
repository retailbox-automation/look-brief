"""SQLite persistence: sessions, briefs, zone reviews, agreements, attestations, unit ledger, IP usage."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, mode TEXT NOT NULL, sample_id TEXT, created_at REAL NOT NULL,
  ip_hash TEXT, consent_at REAL, status TEXT NOT NULL, step TEXT, error TEXT,
  state_json TEXT, units_spent INTEGER NOT NULL DEFAULT 0, deleted_at REAL, owner_token TEXT
);
CREATE TABLE IF NOT EXISTS briefs (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, bride_token TEXT NOT NULL, artist_token TEXT NOT NULL,
  version INTEGER NOT NULL, created_at REAL NOT NULL, snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  brief_id TEXT NOT NULL, version INTEGER NOT NULL, zone TEXT NOT NULL, status TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL, PRIMARY KEY (brief_id, version, zone)
);
CREATE TABLE IF NOT EXISTS agreements (
  brief_id TEXT NOT NULL, version INTEGER NOT NULL, role TEXT NOT NULL, at REAL NOT NULL,
  reviews_sha TEXT NOT NULL DEFAULT '', PRIMARY KEY (brief_id, version, role)
);
CREATE TABLE IF NOT EXISTS attestations (
  brief_id TEXT NOT NULL, version INTEGER NOT NULL, json TEXT NOT NULL, issued_at REAL NOT NULL,
  PRIMARY KEY (brief_id, version)
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, session_id TEXT, op TEXT NOT NULL,
  units INTEGER NOT NULL, task_id TEXT, ok INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ip_usage (
  ip_hash TEXT NOT NULL, day TEXT NOT NULL, sessions INTEGER NOT NULL, PRIMARY KEY (ip_hash, day)
);
"""

REVIEW_STATUSES = ("do", "swap", "discuss")


def new_id(nbytes: int = 9) -> str:
    return secrets.token_urlsafe(nbytes)


def day_utc(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t or time.time()))


class Store:
    def __init__(self, path: Path, ip_salt: str = ""):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._salt = ip_salt or new_id(16)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, args)

    def ip_hash(self, ip: str) -> str:
        return hashlib.sha256((self._salt + ip).encode()).hexdigest()[:20]

    # ---------- sessions ----------
    def create_session(self, mode: str, sample_id: str | None, ip: str, consent: bool) -> tuple[str, str]:
        """Returns (session id, owner token). The owner token is the only key to the session routes."""
        sid, owner = new_id(12), new_id(24)
        now = time.time()
        self._exec("INSERT INTO sessions (id, mode, sample_id, created_at, ip_hash, consent_at, status, owner_token) "
                   "VALUES (?,?,?,?,?,?,?,?)",
                   (sid, mode, sample_id, now, self.ip_hash(ip), now if consent else None, "new", owner))
        return sid, owner

    def is_owner(self, sid: str, token: str | None) -> bool:
        row = self._exec("SELECT owner_token FROM sessions WHERE id=?", (sid,)).fetchone()
        return bool(row and token and row["owner_token"] and secrets.compare_digest(token, row["owner_token"]))

    def interrupt_stale_runs(self, older_than: float) -> int:
        """Sessions left in new/running by a restart can never finish: mark them as interrupted."""
        cur = self._exec("UPDATE sessions SET status='error', error='interrupted' "
                         "WHERE status IN ('new','running') AND created_at < ?", (older_than,))
        return cur.rowcount

    def oldest_replay_sessions(self, keep: int) -> list[str]:
        rows = self._exec("SELECT id FROM sessions WHERE mode='replay' AND deleted_at IS NULL "
                          "ORDER BY created_at DESC LIMIT -1 OFFSET ?", (keep,)).fetchall()
        return [r["id"] for r in rows]

    def session(self, sid: str) -> dict | None:
        row = self._exec("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["state"] = json.loads(d.pop("state_json") or "null")
        return d

    def update_session(self, sid: str, **fields: object) -> None:
        if "state" in fields:
            fields["state_json"] = json.dumps(fields.pop("state"))
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE sessions SET {cols} WHERE id=?", (*fields.values(), sid))

    def add_units(self, sid: str, units: int) -> None:
        self._exec("UPDATE sessions SET units_spent = units_spent + ? WHERE id=?", (units, sid))

    def expired_sessions(self, mode: str, older_than: float) -> list[str]:
        rows = self._exec("SELECT id FROM sessions WHERE mode=? AND deleted_at IS NULL AND created_at < ?",
                          (mode, older_than)).fetchall()
        return [r["id"] for r in rows]

    # ---------- ledger / limits ----------
    def ledger_add(self, sid: str | None, op: str, units: int, task_id: str, ok: bool) -> None:
        self._exec("INSERT INTO ledger (at, session_id, op, units, task_id, ok) VALUES (?,?,?,?,?,?)",
                   (time.time(), sid, op, units, task_id, 1 if ok else 0))

    def live_units_spent(self) -> int:
        row = self._exec("SELECT COALESCE(SUM(units),0) AS u FROM ledger WHERE ok=1").fetchone()
        return int(row["u"])

    def ip_sessions_today(self, ip: str, kind: str = "live") -> int:
        row = self._exec("SELECT sessions FROM ip_usage WHERE ip_hash=? AND day=?",
                         (self.ip_hash(f"{kind}:{ip}"), day_utc())).fetchone()
        return int(row["sessions"]) if row else 0

    def count_ip_session(self, ip: str, kind: str = "live") -> None:
        self._exec("INSERT INTO ip_usage (ip_hash, day, sessions) VALUES (?,?,1) "
                   "ON CONFLICT(ip_hash, day) DO UPDATE SET sessions = sessions + 1",
                   (self.ip_hash(f"{kind}:{ip}"), day_utc()))

    # ---------- briefs ----------
    def create_brief(self, session_id: str, snapshot: dict) -> dict:
        bid = new_id(9)
        bride, artist = new_id(18), new_id(18)
        self._exec("INSERT INTO briefs (id, session_id, bride_token, artist_token, version, created_at, snapshot_json) "
                   "VALUES (?,?,?,?,?,?,?)", (bid, session_id, bride, artist, 1, time.time(), json.dumps(snapshot)))
        return {"id": bid, "bride_token": bride, "artist_token": artist, "version": 1}

    def brief(self, bid: str) -> dict | None:
        row = self._exec("SELECT * FROM briefs WHERE id=?", (bid,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["snapshot"] = json.loads(d.pop("snapshot_json"))
        return d

    def revise_brief(self, bid: str, snapshot: dict) -> int:
        b = self.brief(bid)
        if b is None:
            raise KeyError(bid)
        version = int(b["version"]) + 1
        self._exec("UPDATE briefs SET version=?, snapshot_json=? WHERE id=?", (version, json.dumps(snapshot), bid))
        return version

    def role_for(self, bid: str, token: str) -> str | None:
        b = self.brief(bid)
        if b is None or not token:
            return None
        if secrets.compare_digest(token, b["bride_token"]):
            return "bride"
        if secrets.compare_digest(token, b["artist_token"]):
            return "artist"
        return None

    def set_review(self, bid: str, version: int, zone: str, status: str, note: str) -> bool:
        """Upsert one zone review. If it changed anything, every agreement on this version is withdrawn, so a
        signature can only cover the review state both people agreed to. Returns True if it changed."""
        if status not in REVIEW_STATUSES:
            raise ValueError(status)
        note = note[:500]
        old = self.reviews(bid, version).get(zone)
        if old and old["status"] == status and old["note"] == note:
            return False
        self._exec("DELETE FROM agreements WHERE brief_id=? AND version=?", (bid, version))
        self._exec("INSERT INTO reviews (brief_id, version, zone, status, note, updated_at) VALUES (?,?,?,?,?,?) "
                   "ON CONFLICT(brief_id, version, zone) DO UPDATE SET status=excluded.status, note=excluded.note, "
                   "updated_at=excluded.updated_at", (bid, version, zone, status, note, time.time()))
        return True

    def reviews(self, bid: str, version: int) -> dict[str, dict]:
        rows = self._exec("SELECT zone, status, note, updated_at FROM reviews WHERE brief_id=? AND version=?",
                          (bid, version)).fetchall()
        return {r["zone"]: dict(r) for r in rows}

    def reviews_sha(self, bid: str, version: int) -> str:
        rv = self.reviews(bid, version)
        canon = json.dumps({z: [r["status"], r["note"]] for z, r in rv.items()}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canon.encode()).hexdigest()

    def agree(self, bid: str, version: int, role: str) -> None:
        """Record agreement together with the hash of the reviews the person saw at that moment."""
        self._exec("INSERT OR REPLACE INTO agreements (brief_id, version, role, at, reviews_sha) VALUES (?,?,?,?,?)",
                   (bid, version, role, time.time(), self.reviews_sha(bid, version)))

    def agreements(self, bid: str, version: int) -> dict[str, float]:
        rows = self._exec("SELECT role, at FROM agreements WHERE brief_id=? AND version=?", (bid, version)).fetchall()
        return {r["role"]: r["at"] for r in rows}

    def agreement_shas(self, bid: str, version: int) -> dict[str, str]:
        rows = self._exec("SELECT role, reviews_sha FROM agreements WHERE brief_id=? AND version=?",
                          (bid, version)).fetchall()
        return {r["role"]: r["reviews_sha"] for r in rows}

    def save_attestation(self, bid: str, version: int, att: dict) -> None:
        self._exec("INSERT OR REPLACE INTO attestations (brief_id, version, json, issued_at) VALUES (?,?,?,?)",
                   (bid, version, json.dumps(att), time.time()))

    def attestation(self, bid: str, version: int) -> dict | None:
        row = self._exec("SELECT json FROM attestations WHERE brief_id=? AND version=?", (bid, version)).fetchone()
        return json.loads(row["json"]) if row else None
