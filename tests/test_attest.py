import base64

from lookbrief import attest


def test_sign_verify_and_tamper(tmp_path):
    s = attest.load_signer(key_file=tmp_path / "k")
    att = s.sign({"brief_id": "b1", "version": 1, "zones": [{"zone": "lips", "status": "do"}]})
    pub = s.public_jwk_like()["public_key_b64"]
    assert attest.verify(att, pub)
    att["payload"]["zones"][0]["status"] = "swap"
    assert not attest.verify(att, pub)


def test_key_persists_and_env_key_works(tmp_path):
    a = attest.load_signer(key_file=tmp_path / "k")
    b = attest.load_signer(key_file=tmp_path / "k")
    assert a.key_id == b.key_id
    assert oct((tmp_path / "k").stat().st_mode & 0o777) == "0o600"
    seed = base64.b64encode(bytes(range(32))).decode()
    c = attest.load_signer(key_b64=seed)
    assert attest.verify(c.sign({"x": 1}), c.public_jwk_like()["public_key_b64"])


def test_other_key_fails(tmp_path):
    a = attest.load_signer(key_file=tmp_path / "a")
    b = attest.load_signer(key_file=tmp_path / "b")
    assert not attest.verify(a.sign({"x": 1}), b.public_jwk_like()["public_key_b64"])


def test_ephemeral_key_is_new_each_time_and_embedded():
    a = attest.load_signer(ephemeral=True)
    b = attest.load_signer(ephemeral=True)
    assert a.key_id != b.key_id
    att = a.sign({"x": 1})
    assert att["public_key_b64"] == a.public_jwk_like()["public_key_b64"] and attest.verify(att, att["public_key_b64"])
