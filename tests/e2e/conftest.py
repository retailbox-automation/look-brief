import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    url = os.environ.get("LOOKBRIEF_E2E_URL")
    if url:  # run the smoke against a deployed instance
        yield url.rstrip("/")
        return
    port = _free_port()
    env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1", "LOOKBRIEF_LIVE": "0",
           "LOOKBRIEF_DATA": str(tmp_path_factory.mktemp("data")), "LOOKBRIEF_ATTEST_EPHEMERAL": "1",
           "YOUCAM_API_KEY": ""}
    proc = subprocess.Popen([sys.executable, "-m", "lookbrief"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)
