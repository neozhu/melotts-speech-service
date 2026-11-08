"""Real HTTP/CPU inference verification; no mocks, no silent skips."""

import argparse
import array
import concurrent.futures
import io
import json
import math
import os
import platform
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path


class ServiceClient:
    def __init__(self, base_url: str, key: str):
        self.base_url = base_url.rstrip("/")
        self.key = key

    def request(self, path, body=None, *, authenticated=True, timeout=600):
        headers = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.key}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()


def wait_ready(client, timeout=1800):
    deadline = time.monotonic() + timeout
    saw_live = False
    while time.monotonic() < deadline:
        try:
            status, _, _ = client.request("/health/live", authenticated=False, timeout=3)
            saw_live |= status == 200
            status, _, _ = client.request("/health/ready", authenticated=False, timeout=3)
            if status == 200:
                assert saw_live, "Liveness failed"
                return
            assert status == 503, f"Unexpected readiness status {status}"
        except (OSError, TimeoutError):
            pass
        time.sleep(2)
    raise AssertionError("Readiness did not pass before the startup deadline")


def decode_audio(audio: bytes, fmt: str) -> float:
    assert len(audio) > 128, "Audio response is empty or too short"
    if fmt == "wav":
        with wave.open(io.BytesIO(audio), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() >= 16000
    else:
        assert audio.startswith(b"ID3") or (audio[0] == 255 and audio[1] & 224 == 224)
    # Decode the entire response and reject silent, corrupt or non-finite PCM.
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        input=audio,
        capture_output=True,
        timeout=60,
        check=True,
    )
    samples = array.array("f")
    samples.frombytes(decoded.stdout)
    assert len(samples) >= 1200, "Audio is shorter than 50ms"
    assert all(math.isfinite(sample) for sample in samples), "Non-finite audio"
    assert max(abs(sample) for sample in samples) > 0.001, "Silent audio"
    return len(samples) / 24000


def synthesize(client, text, voice="zh", fmt="wav", speed=1.0):
    started = time.perf_counter()
    status, headers, audio = client.request(
        "/v1/audio/speech",
        {
            "model": "melotts",
            "input": text,
            "voice": voice,
            "response_format": fmt,
            "speed": speed,
        },
    )
    elapsed = time.perf_counter() - started
    assert status == 200, f"Synthesis failed with HTTP {status}"
    assert headers["Content-Type"] == ("audio/wav" if fmt == "wav" else "audio/mpeg")
    duration = decode_audio(audio, fmt)
    return {
        "latency_seconds": elapsed,
        "audio_seconds": duration,
        "rtf": elapsed / duration,
        "bytes": len(audio),
    }


def verify_overload(client):
    barrier = threading.Barrier(12)

    def request():
        barrier.wait(timeout=10)
        return client.request(
            "/v1/audio/speech",
            {
                "model": "melotts",
                "voice": "zh",
                "response_format": "wav",
                "input": "这是并发测试，我们正在检查语音服务的队列和资源限制。" * 6,
            },
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(request) for _ in range(12)]
        time.sleep(0.1)
        started = time.perf_counter()
        assert client.request("/health/live", authenticated=False, timeout=3)[0] == 200
        assert time.perf_counter() - started < 3, "Liveness blocked during inference"
        responses = [future.result(timeout=600) for future in futures]
    statuses = [status for status, _, _ in responses]
    assert 429 in statuses, "Overload did not return 429"
    assert 200 in statuses, "No overload request succeeded"
    assert set(statuses) <= {200, 429}, f"Unexpected overload statuses {statuses}"
    for status, headers, audio in responses:
        if status == 429:
            assert headers["Retry-After"]
        else:
            decode_audio(audio, "wav")
    return {"accepted": statuses.count(200), "rejected": statuses.count(429)}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def verify(client, soak=100, benchmark_samples=5):
    wait_ready(client)
    assert client.request("/v1/models", authenticated=False)[0] == 401
    assert client.request("/v1/audio/voices", authenticated=False)[0] == 401
    assert client.request("/v1/audio/speech", {"input": "test"}, authenticated=False)[0] == 401
    assert client.request("/v1/audio/speech", {"model": "bad", "input": "test"})[0] == 400
    voices = json.loads(client.request("/v1/audio/voices")[2])["voices"]
    assert {voice["id"] for voice in voices} == {
        "zh",
        "en-us",
        "en-br",
        "en-au",
        "en-india",
        "en-default",
    }
    cases = [
        ("mandarin", "你好，今天的天气很好，欢迎使用本地语音服务。", "zh"),
        ("mixed", "你好，Docker 和 Python 服务正常，OpenAI API 已经准备好了。", "zh"),
        ("english", "Hello, this is the local English speech service.", "en-us"),
    ]
    report = {
        "cases": {},
        "hardware": {"client_platform": platform.platform(), "client_cpu_count": os.cpu_count()},
    }
    for name, text, voice in cases:
        for fmt in ("wav", "mp3"):
            report["cases"][name + "_" + fmt] = synthesize(client, text, voice, fmt)
    for voice in voices:
        if voice["language"] == "EN":
            synthesize(client, "This verifies the configured English voice.", voice["id"])
    for voice, phrase in (("zh", "你好，语速测试。"), ("en-us", "Hello, speed test.")):
        for speed in (0.25, 4.0):
            synthesize(client, phrase, voice, speed=speed)

    from openai import OpenAI

    with OpenAI(api_key=client.key, base_url=client.base_url + "/v1", timeout=600) as sdk:
        audio = sdk.audio.speech.create(
            model="tts-1", voice="alloy", input="你好，SDK 测试。", response_format="mp3"
        )
        decode_audio(audio.content, "mp3")

    report["overload"] = verify_overload(client)
    for index in range(soak):
        _, text, voice = cases[index % len(cases)]
        synthesize(client, text, voice, "wav" if index % 2 else "mp3")
        if index % 10 == 0:
            assert client.request("/health/ready", authenticated=False)[0] == 200
    report["soak_requests"] = soak
    report["benchmarks"] = {}
    for name, text in (
        ("short_30_codepoints", (cases[0][1] * 2)[:30]),
        ("medium_150_codepoints", (cases[0][1] * 10)[:150]),
        ("mixed", cases[1][1]),
    ):
        results = [synthesize(client, text) for _ in range(benchmark_samples)]
        latencies = [result["latency_seconds"] for result in results]
        rtfs = [result["rtf"] for result in results]
        report["benchmarks"][name] = {
            "samples": benchmark_samples,
            "codepoints": len(text),
            "p50_seconds": statistics.median(latencies),
            "p95_seconds": percentile(latencies, 0.95),
            "p50_rtf": statistics.median(rtfs),
            "p95_rtf": percentile(rtfs, 0.95),
        }
    assert client.request("/health/ready", authenticated=False)[0] == 200
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--report", type=Path, default=Path("smoke-report.json"))
    parser.add_argument("--ready-only", action="store_true")
    parser.add_argument("--soak", type=int, default=100)
    args = parser.parse_args()
    client = ServiceClient(args.url, os.environ["API_KEY"])
    if args.ready_only:
        wait_ready(client)
        synthesize(client, "你好，缓存重启测试。")
        synthesize(client, "Hello, cached restart test.", "en-us", "mp3")
    else:
        report = verify(client, args.soak)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
