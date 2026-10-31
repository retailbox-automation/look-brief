#!/usr/bin/env python3
"""Verify a Look Brief agreed-look card offline.

    python scripts/verify_card.py look-brief-<id>.json [--key-url https://lookbrief.retailbox-automation.com/.well-known/lookbrief-attest.json]
                                                        [--images DIR]

Checks: (1) the Ed25519 signature over the canonical payload, with the public key embedded in the card;
(2) optionally, that this key is the one the server publishes right now (the public demo makes a new key
at every restart, so an older card verifies against its embedded key but no longer matches the live one);
(3) optionally, that image files in DIR hash to the values the card commits to.
Needs only the `cryptography` package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lookbrief.attest import verify  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("card", type=Path)
    ap.add_argument("--key-url")
    ap.add_argument("--images", type=Path)
    a = ap.parse_args()
    att = json.loads(a.card.read_text())
    ok = verify(att, att["public_key_b64"])
    print(f"signature with embedded key {att['key_id']}: {'VALID' if ok else 'INVALID'}")
    rc = 0 if ok else 1
    if a.key_url:
        with urllib.request.urlopen(a.key_url, timeout=20) as r:
            live = json.load(r)
        same = live["public_key_b64"] == att["public_key_b64"]
        print(f"server key now {live['key_id']}: {'matches' if same else 'differs (server restarted since signing)'}")
    if a.images:
        for name, digest in att["payload"]["images_sha256"].items():
            files = list(a.images.glob(f"{name}.*"))
            if not files:
                print(f"image {name}: not provided")
                continue
            got = hashlib.sha256(files[0].read_bytes()).hexdigest()
            print(f"image {name}: {'matches' if got == digest else 'DIFFERS'}")
            rc = rc or (0 if got == digest else 1)
    p = att["payload"]
    print(f"brief {p['brief_id']} v{p['version']} · agreed {p['agreed_at']} · recipe sha256 {p['recipe_sha256'][:16]}…")
    for z in p["zones"]:
        print(f"  {z.get('label', z['zone']):16s} {z.get('product_hex', ''):8s} {z['status']:8s} {z.get('note', '')}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
