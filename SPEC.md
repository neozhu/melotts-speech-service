# MeloTTS Speech Service — Engineering SPEC

- Version: 1.0-draft
- Project: `melotts-speech-service`
- Target: Linux amd64, Docker Compose, 8 vCPU / 8 GiB host (service limits: 6 CPU / 6 GiB)
- Tech: Python 3.12, FastAPI, MeloTTS, PyTorch CPU, FFmpeg
- Distribution: GHCR (`ghcr.io/<owner>/melotts-speech-service`)
- Status: Implementation contract; **not yet an implemented/runnable service**

## 1. Objective

Build a self-hosted, CPU-only TTS server that is compatible with the OpenAI speech-generation API and can be called by AstrBot / OpenAI SDK. It must synthesize natural Mandarin with occasional English terms, offer full English output, run under Docker, and publish images using only the `latest` tag while recording immutable digests. Tests run during development, not during image publication.

Principles: Chinese-first, small surface, one process, bounded concurrency, reproducible build, privacy by default, no proprietary cloud dependency during inference. The image is deployable with outbound access on the first startup; downloaded models must be cached on a named Docker volume. Do **not** claim offline startup until offline/bundled-model mode is explicitly implemented and verified.

## 2. Scope

### Must-have (v1.0)

- `POST /v1/audio/speech` accepting JSON and responding with binary audio.
- `GET /v1/models`, `GET /v1/audio/voices` (voices is an explicit extension).
- `GET /health/live`, `GET /health/ready`.
- Mandarin `ZH` engine uses upstream `ZH_MIX_EN` behavior; standalone `EN` engine with configured English voice IDs.
- MP3 and WAV, selectable by `response_format`; non-streaming, synchronous response.
- Optional Bearer API key; when `API_KEY` is non-empty, all `/v1/*` endpoints are protected. Do not log secrets or full text.
- Single Uvicorn worker, in-memory model registry, bounded requests; no Redis, database, UI, GPU, SaaS, voice cloning or training.
- Docker Compose example; non-root runtime user; model cache persisted in `/data/hf`; latest-only images on GHCR with recorded digests.
- PR/main development lint/unit tests; manual real Chinese, mixed and English checks during development. Main-push/manual publication builds and pushes without repeating tests.

### Explicit non-goals

- OpenAI `/v1/audio/transcriptions`, `/v1/audio/translations`, Realtime, SSML, `instructions`, `stream_format`, streaming chunks, OpenAI original voice identity, audio cloning, web dashboard.
- HTTP API compatibility does not imply voice timbre compatibility with OpenAI's hosted voices.

## 3. Upstream integration and dependency strategy

- Upstream: `https://github.com/myshell-ai/MeloTTS` (MIT); pin upstream commit SHA, never pull unpinned `main` during release.
- Official upstream `melo/init_downloads.py` initializes **six language models**, so **do not** run this wholesale; load/download only ZH and EN.
- Chinese TTS path uses `ZH_MIX_EN`, and lazily resolves `bert-base-multilingual-uncased` text features; English uses `bert-base-uncased`. Both the TTS checkpoint and BERT/tokenizer assets must be counted in cache, memory, and warm-up checks.
- Pin Python 3.12, CPU-only matching PyTorch/torchaudio wheels, Transformers and HuggingFace Hub versions in a lock file. Use frontend versions with Python 3.12 wheels, and validate upgrades during development. Avoid unqualified latest PyTorch: `torch.load` behavior and ABI compatibility can change. Use SHA256 manifests for downloaded checkpoints, pin HF model revisions where possible; do not load untrusted `.pth` files.
- Production Dockerfile should use `python:3.12-slim-bookworm` (ideally pinned digest), install FFmpeg, libsndfile1 and only necessary build dependencies; keep runtime image lean, remove APT index, execute as unprivileged UID 10001.
- Runtime model cache `/data/hf`, `HF_HOME=/data/hf`, `XDG_CACHE_HOME=/data/cache`, `HOME=/data`. On startup preload the Chinese model and run **a short actual inference** so `/health/ready` means usable output, not only checkpoint presence. English may lazy-load under the same mutex; its first request is allowed to be slower.
- If cached assets are missing and download fails, readiness remains 503; expose actionable error logs without secrets. Startup requires outbound download access unless assets were pre-seeded in the volume.

## 4. API contract

### `POST /v1/audio/speech`

Example:

```http
POST /v1/audio/speech HTTP/1.1
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

```json
{
  "model": "melotts",
  "input": "你好，我是阿拉蕾。今天 Docker 服务正常。",
  "voice": "zh",
  "response_format": "mp3",
  "speed": 1.0
}
```

- `model`: accept `melotts` and `tts-1` as aliases; return 400 for unknown models. `tts-1` is a protocol alias only, not a claim of identical quality.
- `input`: required nonempty UTF-8 text after trimming; default maximum 500 Unicode code points, configurable up to an enforced upper bound of 1000. Reject rather than silently truncate. Strip/normalize control characters and repeated whitespace; do not remove English technical tokens.
- `voice`: canonical `zh` → upstream `ZH`, `en-us` → `EN-US`, `en-br` → `EN-BR`, `en-au` → `EN-AU`, `en-india` → `EN_INDIA`, `en-default` → `EN-Default`; optionally accept `ZH`, `EN-US` case-insensitively. `alloy` may map to `zh` for SDK compatibility, documented as an alias, not OpenAI timbre equivalence.
- `response_format`: exactly `wav` or `mp3` in v1; default `mp3`; any other value gets 400 (`invalid_response_format`).
- `speed`: default 1.0, accept OpenAI-compatible 0.25–4.0; validate that MeloTTS remains functional at extreme values; quality is optimized for 0.8–1.2.
- Success: HTTP 200 and `Content-Type: audio/wav` or `audio/mpeg`, binary audio, `Content-Disposition: inline`; no JSON-wrapped base64. Generate PCM/WAV using MeloTTS and encode MP3 via safe `subprocess.run([...])` argument list (no shell), bounded timeout, predictable bitrate, proper error conversion.
- Error format: `{"error":{"message":"...","type":"invalid_request_error","param":"voice","code":"invalid_voice"}}`. Return 400 on validation/unsupported values; 401 for auth failure; 429 on full concurrency/queue (with `Retry-After`); 503 if model unready; 500 only for unexpected failures (no stack traces to clients).
- No permanent generated speech files; use BytesIO or unique temporary directory cleaned in `finally`.
- `GET /v1/models`: `{"object":"list","data":[{"id":"melotts","object":"model","owned_by":"local"},{"id":"tts-1","object":"model","owned_by":"local"}]}`.
- `GET /v1/audio/voices`: enumerate exactly available configured voice IDs, JSON with `voices` list.
- `/health/live`: 200 while process responsive; `/health/ready`: 200 only once ZH inference can generate valid WAV, otherwise 503. Both must not require Bearer token, but do not expose private details.

## 5. Resource & concurrency requirements

- Exactly `uvicorn --workers 1`; one engine registry per process. Model initialization occurs once per language; protect model instantiation and inference with locks.
- Start with inference concurrency = **1**; maximum waiting requests = **4**, excess requests fail fast with 429. Avoid blocking the event loop; use `asyncio.to_thread`/executor with bounded work submission. No unlimited pending task queue.
- `torch.set_num_threads(4)`, `torch.set_num_interop_threads(1)` before first inference; `OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4`; Docker Compose cap 6 CPU and 6 GiB RAM.
- `/health/live` must stay responsive during synthesis. Use model processing timeout with realistic semantics: a thread executing native inference cannot be forcibly canceled safely; reject queued work after deadline and document lack of hard cancellation for running inference.
- First-start network downloads and model warm-up must not make the health-check falsely report ready.
- No user-supplied file paths, URLs, checkpoint names or model repository IDs in TTS requests (prevent SSRF/path traversal).
- Basic diagnostics: JSON logs with request ID, voice, status, elapsed_ms, synthesis_ms, encoded bytes; default do not log input text, token, full headers or audio body. Optional `/metrics` is out of scope for v1.

## 6. Environment configuration

| Variable | Default | Purpose |
|---|---|---|
| `API_KEY` | empty (dev only) | Bearer token; production must set a nonempty secret |
| `HOST` | `0.0.0.0` | HTTP bind |
| `PORT` | `8000` | HTTP port |
| `TTS_LANGUAGES` | `ZH,EN` | Enabled model set |
| `TTS_PRELOAD_LANGUAGES` | `ZH` | Preload and warm before readiness |
| `TTS_DEFAULT_VOICE` | `zh` | Default voice |
| `TTS_MAX_TEXT_LENGTH` | `500` | Max input code points |
| `TTS_MAX_CONCURRENCY` | `1` | Active inference limit; enforce v1 limit 1 |
| `TTS_MAX_QUEUE` | `4` | Max waiting requests |
| `TTS_CPU_THREADS` | `4` | PyTorch intra-op threads |
| `TTS_INTEROP_THREADS` | `1` | PyTorch inter-op threads |
| `HF_HOME` | `/data/hf` | HuggingFace cache |
| `XDG_CACHE_HOME` | `/data/cache` | Other tokenizer/model caches |
| `LOG_LEVEL` | `INFO` | Avoid user text in logs |

## 7. Required repository tree

```text
melotts-speech-service/
├── app/
│   ├── __init__.py
│   ├── main.py                  # app lifespan, routers, HTTP exception mapping
│   ├── config.py                # pydantic settings
│   ├── api/{speech,models,health}.py
│   ├── schemas/speech.py
│   └── services/{melo_engine,audio_encoder,voice_map}.py
├── tests/
│   ├── unit/                   # fully mocked model/encoding/auth/error cases
│   └── integration/            # real CPU tests (runner or local Docker)
├── scripts/smoke.sh            # provided with this SPEC
├── requirements-ci.txt         # minimal deps for mock tests, no heavyweight model downloads
├── requirements.lock           # pinned production dependencies incl. CPU torch
├── Dockerfile                  # multi-stage, non-root, cache volume
├── deploy/{compose.yaml,.env.example}
├── .github/workflows/{ci.yml,publish.yml}
├── .dockerignore
├── pyproject.toml
├── README.md
└── SPEC.md
```

The included archive intentionally contains the SPEC, CI/CD scripts and deployment examples, **not** the application implementation; developer/agent must implement the missing files before a green release is possible.

## 8. Tests, CI and release

- Unit tests do not fetch ML model files. Mock `TTS` and audio encoder. Test 401/400/429/503, valid WAV/MP3 MIME, alias mapping, SDK request shape, input length, wrong voice, blank content, secret omission, concurrent requests.
- Manual end-to-end development checks build the exact Dockerfile into a local image, launch with 6 CPU / 6 GiB, wait for readiness, synthesize real Chinese, mixed Mandarin/English and standalone English text, and validate decoded WAV/MP3. These checks are not repeated in the publish workflow.
- `.github/workflows/ci.yml`: PR and main push + reusable workflow; `ruff check`, `pytest -q tests/unit`.
- `.github/workflows/publish.yml`: publish on pushes to `main` or manual run. Log into GHCR with the configured `MY_TOKEN` secret, then build and push directly. Do not call the CI workflow or run unit/inference tests during publishing. Use official Docker actions, Buildx cache, provenance and SBOM. Output the immutable image digest.
- Publish only `latest` on every successful build, updating the existing tag. No SemVer or SHA image tags and no Git version tag requirement. Record the source commit and immutable digest for provenance and rollback.
- First GitHub Packages image may be private; to allow anonymous `docker pull`, explicitly change GHCR package visibility to Public after first publication. Configure the workflow's existing `MY_TOKEN` secret with package publication permission.
- Deployment example uses `.env` for selected `TTS_IMAGE` and `API_KEY`; `latest` follows successful publishes and `@sha256:<digest>` selects a specific verified build.

## 9. Definition of Done

1. `docker compose -f deploy/compose.yaml up -d` works after `.env` is filled, with network on first boot and persistent model volume.
2. `GET /health/live` returns 200; ready=503 until a real Mandarin warm-up produces valid audio; ready=200 afterward.
3. `POST /v1/audio/speech` works from OpenAI Python SDK via custom `base_url`, with model `melotts` or `tts-1`, and produces playable MP3/WAV.
4. Chinese standard phrase, Chinese + `Docker/Python/OpenAI API`, and full-English phrase pass real synthesis test.
5. On 8 CPU/8 GiB host, service stays within `cpus: 6.0` and `mem_limit: 6g`, no OOM during a 100-request sequential soak test, and bounded overload returns 429.
6. Record p50/p95 synthesis latency and RTF for short (30 chars), medium (150 chars), and mixed-text cases; **do not claim a measured target until actual hardware benchmark**. Suggested acceptance: RTF < 1 under warm, single-request conditions; document if not met.
7. Development CI runs lint and unit tests. The independent publish workflow does not repeat tests; it stops on Docker build/publication failure and otherwise updates the GHCR `latest` image and records its SHA256 digest.
8. Logs omit API keys/text content; image runs non-root, has read-only root filesystem, and model downloads persist across container restart.
9. README documents install, API example, AstrBot base_url, network configuration, first-run download and upgrade/rollback commands.

## 10. Risks and tradeoffs

- PyTorch + BERT model memory and first-download time may dominate runtime cost; validate on real 8 GiB host. Reduce supported languages or disable EN to preserve RAM if needed.
- MeloTTS upstream has older dependency assumptions. Resolve a lock set and verify modern Docker builds rather than copying upstream requirements unpinned.
- Original pretrained checkpoints use PyTorch `.pth`; load only verified trusted artifacts, pin source versions/hashes.
- OpenAI API support is limited to the speech endpoint; full OpenAI TTS `stream_format` / PCM / OPUS and new voices are explicitly not implemented.
- If `TTS_PRELOAD_LANGUAGES=ZH`, first stand-alone English request includes EN initialization and may have much higher latency.
- Host-only port bind is safer by default. For AstrBot in another Compose stack, join both containers to the same **user-created internal Docker network**, or expose via authenticated TLS reverse proxy; `localhost` in AstrBot container will not reach this TTS container.

## 11. Reference sources

- Upstream source: https://github.com/myshell-ai/MeloTTS
- Upstream Dockerfile: https://github.com/myshell-ai/MeloTTS/blob/main/Dockerfile
- Upstream Python integration: https://github.com/myshell-ai/MeloTTS/blob/main/docs/install.md
- GitHub GHCR publishing: https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- Docker Build GitHub Actions: https://docs.docker.com/build/ci/github-actions
