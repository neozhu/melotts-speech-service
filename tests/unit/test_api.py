import io
import logging
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ServiceError
from app.main import create_app


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x01\x10" * 2400)
    return output.getvalue()


@pytest.fixture
def engine():
    mock = Mock()
    mock.warmup.return_value = None
    mock.synthesize.return_value = wav_bytes()
    return mock


@pytest.fixture
def client(engine):
    with TestClient(create_app(Settings(api_key="test-secret"), engine=engine)) as client:
        client.portal.call(client.app.state.service.wait_startup)
        yield client


AUTH = {"Authorization": "Bearer test-secret"}
PAYLOAD = {"model": "melotts", "input": "你好，Docker 服务正常。", "voice": "zh"}


def test_health_and_discovery(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert [m["id"] for m in client.get("/v1/models", headers=AUTH).json()["data"]] == [
        "melotts",
        "tts-1",
    ]
    voices = client.get("/v1/audio/voices", headers=AUTH).json()["voices"]
    assert [v["id"] for v in voices] == ["zh", "en-us", "en-br", "en-au", "en-india", "en-default"]


@pytest.mark.parametrize("path", ["/v1/models", "/v1/audio/voices", "/v1/audio/speech"])
@pytest.mark.parametrize("token", [None, "Bearer wrong", "Basic test-secret", "Bearer"])
def test_auth(client, path, token):
    headers = {"Authorization": token} if token else {}
    response = (
        client.post(path, json=PAYLOAD, headers=headers)
        if path.endswith("speech")
        else client.get(path, headers=headers)
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("fmt,mime", [("wav", "audio/wav"), ("mp3", "audio/mpeg")])
def test_binary_response(client, engine, fmt, mime):
    response = client.post(
        "/v1/audio/speech", headers=AUTH, json={**PAYLOAD, "response_format": fmt}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == mime
    assert response.headers["content-disposition"] == "inline"
    assert response.content == engine.synthesize.return_value


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("model", "tts-evil", "invalid_model"),
        ("voice", "../file", "invalid_voice"),
        ("response_format", "opus", "invalid_response_format"),
        ("input", " \t\x00\n", "invalid_input"),
        ("input", "a" * 501, "invalid_input"),
        ("input", 123, "invalid_input"),
        ("speed", 0.24, "invalid_speed"),
        ("speed", 4.01, "invalid_speed"),
        ("speed", True, "invalid_speed"),
        ("speed", "1.0", "invalid_speed"),
        ("instructions", "talk", "invalid_request"),
    ],
)
def test_invalid_requests(client, field, value, code):
    response = client.post("/v1/audio/speech", headers=AUTH, json={**PAYLOAD, field: value})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["param"] == field


def test_normalization_and_aliases(client, engine):
    response = client.post(
        "/v1/audio/speech",
        headers=AUTH,
        json={
            "model": "tts-1",
            "input": "  你好\x00\t Docker\n API  ",
            "voice": "ALLOY",
            "speed": 0.25,
        },
    )
    assert response.status_code == 200
    assert engine.synthesize.call_args.args == ("你好 Docker API", "zh", 0.25, "mp3")


def test_malformed_json(client):
    response = client.post("/v1/audio/speech", headers=AUTH, content=b"{")
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


def test_failure_does_not_leak_text_or_key(client, engine, caplog):
    engine.synthesize.side_effect = RuntimeError("private text test-secret")
    with caplog.at_level(logging.INFO, logger="speech"):
        response = client.post("/v1/audio/speech", headers=AUTH, json=PAYLOAD)
    assert response.status_code == 500
    assert "private text" not in response.text + caplog.text
    assert "test-secret" not in response.text + caplog.text
    assert PAYLOAD["input"] not in caplog.text
    assert response.headers["x-request-id"]


def test_failed_startup_is_live_but_unready(engine):
    engine.warmup.side_effect = RuntimeError("download failed: private token")
    with TestClient(create_app(Settings(), engine=engine)) as client:
        client.portal.call(client.app.state.service.wait_startup)
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post("/v1/audio/speech", json=PAYLOAD)
        assert response.status_code == 503
        assert "private token" not in response.text


def test_disabled_english(engine):
    with TestClient(create_app(Settings(tts_languages="ZH"), engine=engine)) as client:
        client.portal.call(client.app.state.service.wait_startup)
        assert len(client.get("/v1/audio/voices").json()["voices"]) == 1
        assert (
            client.post("/v1/audio/speech", json={**PAYLOAD, "voice": "en-us"}).status_code == 400
        )


def test_openai_sdk_request(client):
    from openai import OpenAI

    sdk = OpenAI(api_key="test-secret", base_url="http://testserver/v1", http_client=client)
    audio = sdk.audio.speech.create(
        model="tts-1", voice="alloy", input="你好", response_format="wav"
    )
    assert audio.content[:4] == b"RIFF"


def test_overload_has_openai_error_and_retry_after(client, engine):
    engine.synthesize.side_effect = ServiceError(429, "Busy", "rate_limit_exceeded")
    response = client.post("/v1/audio/speech", headers=AUTH, json=PAYLOAD)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"]["type"] == "rate_limit_error"


def test_liveness_stays_responsive_during_startup(engine):
    entered, release = threading.Event(), threading.Event()

    def warmup():
        entered.set()
        assert release.wait(5)

    engine.warmup.side_effect = warmup
    with TestClient(create_app(Settings(), engine=engine)) as client:
        try:
            assert entered.wait(5)
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").status_code == 503
        finally:
            release.set()


def test_liveness_stays_responsive_during_synthesis(client, engine):
    entered, release = threading.Event(), threading.Event()

    def synthesize(*args):
        entered.set()
        assert release.wait(5)
        return wav_bytes()

    engine.synthesize.side_effect = synthesize
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/v1/audio/speech", headers=AUTH, json=PAYLOAD)
        try:
            assert entered.wait(5)
            started = time.perf_counter()
            assert client.get("/health/live").status_code == 200
            assert time.perf_counter() - started < 2
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
