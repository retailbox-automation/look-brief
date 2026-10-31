import json

import httpx
import pytest

from lookbrief.youcam import YouCamClient, YouCamError, redact

KEY = "sk-test-not-a-real-key-000000000000"


def make_transport(script):
    """script: list of (method, path_prefix, status, json) consumed in order."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        method, prefix, status, body = script.pop(0)
        assert request.method == method and request.url.path.startswith(prefix), (request.method, request.url.path)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), calls


SIGNED = "https://bucket.s3.amazonaws.com/x.jpg?X-Amz-Expires=7200&X-Amz-Signature=deadbeef"


def test_upload_task_download_happy_path(tmp_path):
    script = [
        (
            "POST",
            "/s2s/v2.0/file",
            200,
            {
                "data": {
                    "files": [
                        {
                            "file_id": "f1",
                            "requests": [
                                {
                                    "method": "PUT",
                                    "url": "https://upload.example/put",
                                    "headers": {"Content-Type": "image/jpeg"},
                                }
                            ],
                        }
                    ]
                }
            },
        ),
        ("PUT", "/put", 200, b""),
        ("POST", "/s2s/v2.0/task/mu-transfer", 200, {"data": {"task_id": "t1"}}),
        ("GET", "/s2s/v2.0/task/mu-transfer/t1", 200, {"data": {"task_status": "running"}}),
        ("GET", "/s2s/v2.0/task/mu-transfer/t1", 200, {"data": {"task_status": "success", "results": {"url": SIGNED}}}),
        ("GET", "/x.jpg", 200, b"\xff\xd8jpeg"),
    ]
    transport, calls = make_transport(script)
    log = tmp_path / "calls.jsonl"
    c = YouCamClient(KEY, call_log=log, transport=transport, sleep=lambda s: None)
    fid = c.upload(b"abc", "bride.jpg")
    res = c.run_task("mu-transfer", {"src_file_id": fid, "ref_file_id": fid})
    assert (res.task_id, res.units) == ("t1", 2)
    assert c.download(res.result_url) == b"\xff\xd8jpeg"
    text = log.read_text()
    assert KEY not in text, "the API key must never reach the call log"
    assert "X-Amz-Signature" not in text and "<signed-url-redacted>" in text
    assert calls[0][2] == f"Bearer {KEY}" and calls[1][2] is None, "the key must not be sent to the upload URL"


def test_task_error_raises_code_without_units():
    script = [
        ("POST", "/s2s/v2.0/task/mu-transfer", 200, {"data": {"task_id": "t2"}}),
        (
            "GET",
            "/s2s/v2.0/task/mu-transfer/t2",
            200,
            {"status": 200, "data": {"error": "error_ref_no_face", "results": None, "task_status": "error"}},
        ),
    ]
    transport, _ = make_transport(script)
    c = YouCamClient(KEY, transport=transport, sleep=lambda s: None)
    with pytest.raises(YouCamError) as e:
        c.run_task("mu-transfer", {})
    assert e.value.code == "error_ref_no_face"


def test_429_is_retried_with_backoff():
    sleeps = []
    script = [
        ("GET", "/s2s/v1.0/client/credit", 429, {"error": "rate"}),
        ("GET", "/s2s/v1.0/client/credit", 200, {"results": [{"amount": 900}, {"amount": 40}]}),
    ]
    transport, _ = make_transport(script)
    c = YouCamClient(KEY, transport=transport, sleep=sleeps.append)
    assert c.credit() == 940 and sleeps == [1.0]


def test_http_400_surfaces_api_error_code():
    transport, _ = make_transport(
        [
            (
                "POST",
                "/s2s/v2.0/task/makeup-vto",
                400,
                {"error_code": "InvalidParameters", "error_message": "lip_color: style"},
            )
        ]
    )
    c = YouCamClient(KEY, transport=transport, sleep=lambda s: None)
    with pytest.raises(YouCamError) as e:
        c.run_task("makeup-vto", {})
    assert e.value.code == "InvalidParameters" and e.value.http_status == 400


def test_redact_is_recursive():
    out = redact({"a": [SIGNED, {"b": SIGNED}], "c": "https://example.com/ok.jpg"})
    assert json.dumps(out).count("<signed-url-redacted>") == 2 and out["c"] == "https://example.com/ok.jpg"


def test_key_required():
    with pytest.raises(ValueError):
        YouCamClient("")
