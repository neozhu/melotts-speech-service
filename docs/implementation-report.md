# Implementation report

Date: 2026-11-08. Implementation is present; the deployment/release definition of
done remains **unverified** until a Linux Docker run and GHCR release succeed.

## Delivered

- FastAPI speech, model discovery, voice discovery and health endpoints; optional
  Bearer authentication; OpenAI error envelopes and binary MP3/WAV responses.
- Official MeloTTS CPU adapter, Chinese mixed-language path, five English voices,
  immutable frontend/acoustic revisions and verified checkpoint/config hashes.
- Reusable models, serialized native work, one active plus at most four waiting
  requests, queued deadlines, cancellation accounting and actual WAV startup warm-up.
- Pinned Python 3.10/Linux production lock (114 packages, hashed CPU wheels),
  source/base-image pins, non-root multi-stage image, persistent caches, read-only
  Compose deployment and configuration examples.
- PR/main/reusable CI and gated OCI release workflow with real decoding tests,
  overload, 100-request soak, cache restart, latency/RTF report, provenance/SBOM,
  latest-only image tagging and publication digest verification.
- README covering local build, SDK/AstrBot use, networking, configuration,
  first-run downloads, upgrades and rollback.

## Executed verification

Environment: Windows x86-64. Application unit suite executed with CPython 3.10.18.

| Check | Result |
| --- | --- |
| `ruff check app scripts tests` | Passed |
| `pytest -q tests/unit` | 68 passed; no skips |
| `python -m compileall -q app scripts tests` | Passed |
| `bash -n scripts/smoke.sh` (Git Bash) | Passed |
| actionlint 1.7.7 against both workflows | Passed |
| YAML parsing of workflows/Compose | Passed |
| Linux CPython 3.10 dependency resolution and hash lock generation | Passed; no CUDA packages |
| Verified upstream archive preparation / revision injection / dictionary cache | Passed on Python 3.10 |
| `git diff --check` | Passed |

Unit tests mock model inference and subprocess encoding. They exercise auth,
validation, MIME/envelopes, aliases, SDK request compatibility, startup readiness,
responsive health during model work, queue saturation/expiry/cancellation,
recovery, checkpoint verification, latest-only metadata and configuration privacy.
These results do not establish real synthesis or a successful container build.

The independent code review found a configuration-validation secret exposure.
The fix hides input values in Pydantic error text; a regression test was observed
failing before the fix and passing afterward.

## Not executed

Docker and WSL are unavailable on this host. Consequently, no Docker build,
Compose startup, real MeloTTS inference, audio decoding from real inference,
Linux memory/latency benchmark, 100-request real soak, cache restart or GHCR
publication has been performed here. No speed, RTF or memory-fit target is claimed.

The release workflow is implemented and statically validated, but has not been
executed against GitHub or GHCR in this session. OCI import and publication with
preserved attestations/digests require that run for end-to-end verification.

## Image tags and digest

**Published images: none from this session. Immutable digest: unavailable.**

Pushes to `main` and manual dispatch both publish only
`ghcr.io/neozhu/melotts-speech-service:latest`, updating it after verification.
No version tag is required. A successful workflow emits the immutable digest and uploads
`cpu-inference-results-<commit>` containing test results, logs and publication refs.

## Manual actions and limitations

1. On Linux, configure `deploy/.env`, build/start with Compose, and run
   `bash scripts/smoke.sh melotts-speech-service:local smoke-results`.
2. Validate 6-GiB memory fit and latency/RTF on an 8-vCPU host with 8 GiB available.
   Hosted runner performance is not evidence for that hardware profile. Set
   repository variable `TTS_RELEASE_RUNNER` for an appropriate Linux runner.
3. Enable Actions/package write permissions. Push to `main` or manually dispatch the
   workflow. A successful publish is still required to satisfy release completion.
4. Make the first GHCR package public if anonymous pulls are desired; deploy the
   verified digest from the workflow summary. Keep prior digests for rollback.

First startup requires network access. Offline startup is not a verified mode.
The older upstream frontend dependency set and PyTorch checkpoint compatibility
must pass real-image tests. Eager unused-language tokenizer imports add downloads.
Native inference cannot be forcibly cancelled; client timeout retains its occupied
slot until completion. Debian system packages and NLTK dictionary downloads are
resolved at build time despite pinned Python/source/model versions. The `latest`
tag moves on each successful publish; retain verified digests for rollback.
