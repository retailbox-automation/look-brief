"""Thin client for the Perfect Corp YouCam API (server side only — the key never reaches a browser).

Flow per task: POST /s2s/v2.0/file (get an upload URL) -> PUT bytes -> POST /s2s/<ver>/task/<name>
-> poll GET /s2s/<ver>/task/<name>/<task_id> until success/error. A task that ends in `error`
does not consume units (checked in the spike: 954 -> 954). Result URLs expire after 2 hours, so
results are downloaded immediately. Every call is appended to a JSONL call log with signed URLs
redacted and the key never written.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = "https://yce-api-01.makeupar.com"
SIGNED_URL = re.compile(r"https?://[^\s\"']*(?:X-Amz-|Signature=|Expires=)[^\s\"']*")

# Units per successful task (docs + spike debits).
UNITS = {"mu-transfer": 2, "hair-transfer": 2, "makeup-vto": 1, "skin-tone-analysis": 20}
VERSIONS = {"mu-transfer": "v2.0", "hair-transfer": "v2.1", "makeup-vto": "v2.0", "skin-tone-analysis": "v2.0"}


class YouCamError(Exception):
    def __init__(self, code: str, message: str = "", stage: str = "", http_status: int | None = None):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message
        self.stage = stage
        self.http_status = http_status


@dataclass
class TaskResult:
    name: str
    task_id: str
    result_url: str
    seconds: float
    units: int
    raw: dict


def redact(obj: object) -> object:
    """Replace signed/expiring URLs (presigned S3 etc.) with a marker, recursively."""
    if isinstance(obj, str):
        return SIGNED_URL.sub("<signed-url-redacted>", obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def result_url(data: dict) -> str:
    r = data.get("results") or {}
    if isinstance(r, dict) and r.get("url"):
        return str(r["url"])
    if isinstance(r, list) and r and isinstance(r[0], dict):
        first = r[0]
        if first.get("url"):
            return str(first["url"])
        inner = first.get("data") or [{}]
        if inner and inner[0].get("url"):
            return str(inner[0]["url"])
    if data.get("url"):
        return str(data["url"])
    raise YouCamError("no_result_url", "task succeeded but no result URL in response", "poll")


class YouCamClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        call_log: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_every: float = 2.0,
        max_wait: float = 180.0,
    ):
        if not api_key:
            raise ValueError("YouCam API key is required for Live mode")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._log_path = call_log
        self._log_lock = threading.Lock()
        self._sleep = sleep
        self.poll_every = poll_every
        self.max_wait = max_wait
        self._http = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), transport=transport)

    # ---------- plumbing ----------
    def _log(self, rec: dict) -> None:
        if self._log_path is None:
            return
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **rec}
        line = json.dumps(redact(rec), ensure_ascii=False)
        with self._log_lock:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a") as f:
                f.write(line + "\n")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self._base + path
        headers = {"Authorization": f"Bearer {self._key}"}
        delay = 1.0
        for attempt in range(5):
            t0 = time.monotonic()
            try:
                resp = self._http.request(method, url, json=body, headers=headers)
            except httpx.TransportError as e:
                self._log({"method": method, "path": path, "error": type(e).__name__, "attempt": attempt})
                if attempt == 4:
                    raise YouCamError("network_error", str(e), path) from e
                self._sleep(delay)
                delay *= 2
                continue
            sec = round(time.monotonic() - t0, 2)
            try:
                data = resp.json() if resp.content else {}
            except ValueError:
                data = {"_raw": resp.text[:300]}
            self._log({"method": method, "path": path, "code": resp.status_code, "sec": sec,
                       "body": body, "resp": data, "attempt": attempt})
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == 4:
                    raise YouCamError(f"http_{resp.status_code}", str(data)[:200], path, resp.status_code)
                self._sleep(delay)
                delay *= 2
                continue
            if resp.status_code >= 400:
                code = str(data.get("error_code") or data.get("error") or f"http_{resp.status_code}")
                msg = str(data.get("error_message") or data.get("message") or "")
                raise YouCamError(code, msg, path, resp.status_code)
            return data
        raise YouCamError("retries_exhausted", "", path)

    # ---------- public API ----------
    def credit(self) -> int:
        data = self._request("GET", "/s2s/v1.0/client/credit")
        return int(sum(int(r.get("amount", 0)) for r in data.get("results") or []))

    def upload(self, content: bytes, file_name: str, content_type: str = "image/jpeg") -> str:
        data = self._request("POST", "/s2s/v2.0/file", {
            "files": [{"content_type": content_type, "file_name": file_name, "file_size": len(content)}]
        })
        f = data["data"]["files"][0]
        req = f["requests"][0] if isinstance(f.get("requests"), list) else f["requests"]
        headers = req.get("headers") or {}
        t0 = time.monotonic()
        put = self._http.request(req.get("method", "PUT"), req["url"], content=content, headers=headers,
                                 timeout=120.0)
        self._log({"upload_put": file_name, "code": put.status_code, "sec": round(time.monotonic() - t0, 2)})
        if put.status_code not in (200, 201, 204):
            raise YouCamError("upload_failed", f"PUT {put.status_code}", "upload", put.status_code)
        return str(f["file_id"])

    def run_task(self, name: str, body: dict, version: str | None = None) -> TaskResult:
        ver = version or VERSIONS.get(name, "v2.0")
        t0 = time.monotonic()
        start = self._request("POST", f"/s2s/{ver}/task/{name}", body)
        task_id = str(start["data"]["task_id"])
        while time.monotonic() - t0 < self.max_wait:
            self._sleep(self.poll_every)
            data = self._request("GET", f"/s2s/{ver}/task/{name}/{task_id}").get("data") or {}
            status = data.get("task_status")
            if status == "success":
                return TaskResult(name, task_id, result_url(data), round(time.monotonic() - t0, 1),
                                  UNITS.get(name, 0), data)
            if status == "error":
                raise YouCamError(str(data.get("error") or "task_error"), "", "poll")
        raise YouCamError("timeout", f"task {task_id} not finished in {self.max_wait}s", "poll")

    def download(self, url: str) -> bytes:
        resp = self._http.get(url, headers={"User-Agent": "Mozilla/5.0 LookBrief"}, timeout=120.0)
        if resp.status_code != 200:
            raise YouCamError("download_failed", f"GET result {resp.status_code}", "download", resp.status_code)
        return resp.content

    def close(self) -> None:
        self._http.close()
