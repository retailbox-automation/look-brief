"""Server-attested agreement: an Ed25519 signature by the Look Brief server over the agreed brief.

What it proves: this server recorded that the bride link and the artist link both pressed "agree"
on exactly this brief version (zones, statuses, recipe, image hashes) at these times. It is NOT a
personal signature of either person. Anyone can check it offline with the public key
(GET /.well-known/lookbrief-attest.json) — see scripts/verify_card.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ALG = "Ed25519"
STATEMENT = ("The Look Brief server recorded that the bride link and the makeup-artist link both agreed to "
             "this exact brief version. This is a server attestation, not a personal signature.")


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s.encode())


@dataclass
class Signer:
    private: Ed25519PrivateKey

    @property
    def public_raw(self) -> bytes:
        return self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def key_id(self) -> str:
        return hashlib.sha256(self.public_raw).hexdigest()[:16]

    def public_jwk_like(self) -> dict:
        return {"alg": ALG, "key_id": self.key_id, "public_key_b64": b64(self.public_raw)}

    def sign(self, payload: dict) -> dict:
        sig = self.private.sign(canonical(payload))
        return {"payload": payload, "alg": ALG, "key_id": self.key_id, "signature_b64": b64(sig)}


def load_signer(key_b64: str = "", key_file: Path | None = None) -> Signer:
    """Production: raw 32-byte seed in env LOOKBRIEF_ATTEST_KEY (base64, injected by infisical run).
    Local runs: a seed file in the data dir, created on first start."""
    if key_b64:
        return Signer(Ed25519PrivateKey.from_private_bytes(unb64(key_b64)))
    if key_file is None:
        raise ValueError("no attestation key")
    if key_file.exists():
        return Signer(Ed25519PrivateKey.from_private_bytes(key_file.read_bytes()))
    key = Ed25519PrivateKey.generate()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                           serialization.NoEncryption()))
    key_file.chmod(0o600)
    return Signer(key)


def verify(attestation: dict, public_key_b64: str) -> bool:
    pub = Ed25519PublicKey.from_public_bytes(unb64(public_key_b64))
    if hashlib.sha256(unb64(public_key_b64)).hexdigest()[:16] != attestation.get("key_id"):
        return False
    try:
        pub.verify(unb64(attestation["signature_b64"]), canonical(attestation["payload"]))
    except (InvalidSignature, KeyError, ValueError):
        return False
    return True


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
