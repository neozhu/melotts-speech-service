# MeloTTS Speech Service

Local Mandarin, mixed Chinese/English and English speech using FastAPI and the
official [MeloTTS](https://github.com/myshell-ai/MeloTTS) CPU engine. Returns MP3
or PCM WAV through the OpenAI speech API. No database, Redis, GPU or external
inference service is required.

The implementation is present; **Docker inference and GHCR publication have not
been executed in this development session**. See the
[implementation report](docs/implementation-report.md). The contract is [SPEC.md](SPEC.md).

## Build and start

Use Linux x86-64, Docker Engine and Compose v2, 8 vCPU and 8 GiB available RAM.
Compose caps the service at 6 CPUs / 6 GiB. Allow several GB of disk for the image
and model cache. Initial startup requires outbound HTTPS to Hugging Face for
acoustic checkpoints, BERT weights and tokenizer assets; models are not bundled.

```bash
git clone https://github.com/neozhu/melotts-speech-service.git
cd melotts-speech-service/deploy
cp .env.example .env
# Edit .env and replace API_KEY with a long random secret.
# Keep TTS_IMAGE=melotts-speech-service:local for a local build.
docker compose build
docker compose up -d
docker compose logs -f speech
```

From the repository root, use
`docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build`.
Liveness becomes available during startup. Readiness remains 503 until real
Mandarin inference generates valid, non-silent WAV. Download failure leaves the
service live and unready: correct network/cache permissions and restart. English
initializes on its first request unless preloaded; that request can be slower.

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
export API_KEY='the-same-secret-as-in-deploy/.env'
curl --fail-with-body http://127.0.0.1:8000/v1/audio/speech \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"melotts","input":"你好，Docker 和 Python 服务正常。","voice":"zh","response_format":"mp3"}' \
  --output speech.mp3
```

Compose requires a nonempty key, binds to host loopback, drops all capabilities,
disables privilege escalation and uses a read-only root filesystem. UID/GID 10001
owns the named volumes at `/data/hf` and `/data/cache`; `/tmp` is a bounded tmpfs.
Caches survive recreation. Do not use `docker compose down -v` unless deleting
models intentionally. Pre-existing bind mounts must be writable by UID/GID 10001.

## OpenAI SDK and AstrBot

```bash
python -m pip install openai==2.7.1
```

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["API_KEY"], base_url="http://127.0.0.1:8000/v1")
audio = client.audio.speech.create(
    model="melotts", voice="zh", input="你好，OpenAI API 已经准备好了。",
    response_format="mp3",
)
audio.stream_to_file("chinese.mp3")

audio = client.audio.speech.create(
    model="tts-1", voice="en-us", input="Hello, this is a local English voice.",
    response_format="wav",
)
audio.stream_to_file("english.wav")
```

In AstrBot, select an OpenAI-compatible TTS provider, configure the same key,
model `melotts` or `tts-1`, voice `zh`, and a base URL ending in `/v1`.
`localhost` inside another container refers to that container, not this service.
For separate Compose stacks, create a shared network:

```bash
docker network create --internal tts-shared
```

Create `deploy/compose.network.yaml` locally:

```yaml
services:
  speech:
    networks: [default, tts-shared]
networks:
  tts-shared:
    external: true
```

Run `docker compose -f compose.yaml -f compose.network.yaml up -d` from `deploy/`.
Attach AstrBot to `tts-shared` in its Compose configuration and use
`http://speech:8000/v1`. Retain the TTS default network for first-run downloads;
the internal shared network alone has no outbound access. Use an authenticated
TLS reverse proxy for remote access.

## API

| Endpoint | Authentication | Response |
| --- | --- | --- |
| `POST /v1/audio/speech` | Bearer when configured | Binary `audio/mpeg` or `audio/wav` |
| `GET /v1/models` | Bearer when configured | `melotts`, `tts-1` |
| `GET /v1/audio/voices` | Bearer when configured | Enabled IDs, languages and speakers |
| `GET /health/live` | None | Process liveness |
| `GET /health/ready` | None | 200 after warm-up; otherwise 503 |

| Speech field | Accepted values |
| --- | --- |
| `model` | Required: `melotts` or `tts-1` |
| `input` | Required spoken text; default maximum 500 Unicode code points |
| `voice` | Defaults to `TTS_DEFAULT_VOICE` |
| `response_format` | `mp3` (default), `wav` |
| `speed` | Numeric 0.25–4.0; default 1.0; quality optimized for 0.8–1.2 |

Input is trimmed, controls become spaces, and whitespace is collapsed. Blank and
punctuation-only text is rejected. The configured length limit applies after
normalization; raw input also has an absolute 1000-code-point cap. Long inputs
are segmented for frontend processing without deleting content. Unknown fields,
models, voices and formats return 400, including `instructions` and `stream_format`.
Output is a complete, synchronous binary response with `Content-Disposition: inline`.
Streaming chunks, SSML, cloning and other OpenAI audio endpoints are outside v1.

| Voice | Upstream speaker | Engine |
| --- | --- | --- |
| `zh` | `ZH` | `ZH`, with upstream `ZH_MIX_EN` behavior |
| `en-us` | `EN-US` | `EN` |
| `en-br` | `EN-BR` (British) | `EN` |
| `en-au` | `EN-AU` | `EN` |
| `en-india` | `EN_INDIA` | `EN` |
| `en-default` | `EN-Default` | `EN` |

Voice lookup is case-insensitive; `alloy` maps to `zh`, and `EN_INDIA` is accepted.
Use `zh` for mixed text. Disabling EN removes its voices. `tts-1` and `alloy` are
protocol aliases; they do not reproduce OpenAI voice timbre.

Errors use the OpenAI envelope:

```json
{"error":{"message":"Unsupported voice.","type":"invalid_request_error","param":"voice","code":"invalid_voice"}}
```

Authentication failure returns 401; full capacity returns 429 with `Retry-After: 5`;
unready models, queue expiry and encoding failure return 503. Unexpected failures
return a generic 500. `X-Request-ID` correlates requests with JSON diagnostics.
Logs include canonical voice, status, elapsed time, synthesis pipeline time
(including queue/encoding), and encoded bytes. They omit input, secrets, headers
and audio; upstream console output is discarded during model work.

## Configuration and limits

Environment is read once at startup. Compose reads `deploy/.env` when invoked
from `deploy/`; otherwise pass `--env-file deploy/.env`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_KEY` | Empty in app | Optional for development; required by Compose |
| `HOST`, `PORT` | `0.0.0.0`, `8000` | HTTP bind; fixed internally by Compose |
| `TTS_LANGUAGES` | `ZH,EN` | Enabled subset; ZH required |
| `TTS_PRELOAD_LANGUAGES` | `ZH` | Warm before readiness; ZH required |
| `TTS_DEFAULT_VOICE` | `zh` | Must be enabled |
| `TTS_MAX_TEXT_LENGTH` | `500` | 1–1000 code points |
| `TTS_MAX_CONCURRENCY` | `1` | v1 enforces exactly one |
| `TTS_MAX_QUEUE` | `4` | 0–4 waiting slots |
| `TTS_QUEUE_TIMEOUT_SECONDS` | `120` | Waiting deadline only |
| `TTS_ENCODE_TIMEOUT_SECONDS` | `30` | FFmpeg timeout |
| `TTS_CPU_THREADS` | `4` | Intra-op threads; Compose fixes four |
| `TTS_INTEROP_THREADS` | `1` | v1 enforces one |
| `HF_HOME` | `/data/hf` | Persistent model/tokenizer cache |
| `XDG_CACHE_HOME` | `/data/cache` | Other writable caches |
| `LOG_LEVEL` | `INFO` | Diagnostic level |

One process owns one reusable model per loaded language. One worker serializes
initialization, inference and encoding, while async handlers serve health checks.
Capacity defaults to one active plus four waiting requests. Cancelled or expired
queued work is never synthesized; its bounded slot is reclaimed as the worker
drains it. Running native PyTorch work cannot safely be forcibly cancelled.
Timeout/disconnect does not release its slot before completion. Set client/proxy
timeouts accordingly. Shutdown waits for native work; Docker's Compose grace
period is five minutes, after which Docker can terminate the process.

## Pinned dependencies

`requirements.lock` pins all production Python dependencies with SHA256 hashes
for Python 3.12 / Linux x86-64, including matching PyTorch/torchaudio 2.6.0 CPU
wheels, Transformers 4.38.2, tokenizers 0.15.2 and fugashi 1.3.3. These frontend
versions provide Python 3.12 wheels while retaining the upstream BERT API.
The base image is pinned by digest. Debian system packages are resolved at build time.

Official MeloTTS source commit: `209145371cff8fc3bd60d7be902ea69cbdb7965a`.
`scripts/install_melo.py` verifies its archive, copies the official package,
precomputes its writable English dictionary cache, and adds pinned Hugging Face
revision arguments to 16 frontend loading calls. Inference and phonemization
algorithms remain upstream code. This avoids the upstream install hook's full
UniDic download and unrelated training/UI dependencies. UniDic Lite and required
NLTK dictionaries are included in the image.

`app/services/model_assets.py` contains immutable revisions and config/checkpoint
SHA256 manifests. Checkpoints are verified before deserialization. Only ZH/EN
acoustic checkpoints are downloaded. Eager upstream imports also need Japanese,
Korean, French and Spanish tokenizer assets. Chinese mixed speech uses multilingual
uncased BERT, and English uses uncased English BERT. These assets contribute to
first-start downloads, disk and memory. Offline startup is not a verified mode.

After intentionally changing pins, regenerate with:

```bash
python -m pip install uv==0.8.22
uv pip compile requirements.in --python-version 3.12 \
  --python-platform x86_64-unknown-linux-gnu --generate-hashes -o requirements.lock
```

## Tests and releases

Unit tests use mocked engines and require no model downloads:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-ci.txt
ruff check app scripts tests
pytest -q tests/unit
bash -n scripts/smoke.sh
```

Real verification additionally requires Docker and FFmpeg on the test host:

```bash
docker build --platform linux/amd64 -t melotts-speech-service:local .
bash scripts/smoke.sh melotts-speech-service:local smoke-results
```

The script verifies CPU-only Torch, actual Mandarin/mixed/English WAV and MP3
decoding, every English voice, speed extremes, SDK calls, overload, live health,
100 sequential requests, and restart using the same cache volumes. It cleans up
its temporary containers/volumes and writes evidence under `smoke-results/`.
Latency/RTF p50/p95 are recorded for 30-code-point, 150-code-point and mixed cases
(five samples each, not a capacity guarantee). Resource limits/state are recorded.
On hosts with fewer than six logical CPUs the smoke CPU cap is reduced. Use an
8-vCPU / 8-GiB-available Linux host for target-hardware validation.

PR/main CI runs lint and unit tests during development. Publishing runs independently:
pushes to `main` and manual publish runs build and push the CPU image directly,
without rerunning unit tests, starting a container or synthesizing test audio.
Run the real verification script manually during development when needed.
Buildx cache, provenance and SBOM remain enabled. Set repository variable
`TTS_RELEASE_RUNNER` to use a larger or self-hosted Linux build runner;
default: `ubuntu-24.04`.

Every successful publish updates only `ghcr.io/<owner>/<repository>:latest`.
No Git version tag is needed, and no SemVer or SHA image tags are generated.
The workflow summary records the immutable digest, and the image revision label
records the source commit so a specific build can be deployed or rolled back.

Enable Actions with package write permission, then push to `main` or manually
dispatch the publish workflow. Configure the existing `MY_TOKEN` repository
secret with permission to publish the GHCR package.
After the first successful publish, change GHCR package visibility to Public for
anonymous pulls. The image/digest is available only after a successful publish.

For deploy/rollback, set `TTS_IMAGE` in `.env` to the published `@sha256:<digest>`
reference, then run from `deploy/`:

```bash
docker compose pull speech
docker compose up -d --no-build speech
curl --fail http://127.0.0.1:8000/health/ready
```

Use the previous published digest to roll back. Keep volumes across upgrades;
new pinned model revisions use additional disk. Do not substitute untrusted
checkpoint files.
