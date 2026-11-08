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
- Pinned Python 3.12/Linux production lock with hashed CPU wheels,
  source/base-image pins, non-root multi-stage image, persistent caches, read-only
  Compose deployment and configuration examples.
- PR/main development CI and a build-and-push release workflow with provenance/SBOM,
  latest-only image tagging and recorded image digest. Publishing does not rerun
  tests. Manual real-inference scripts cover decoding, overload, a 100-request
  soak, cache restart and latency/RTF reporting during development.
- README covering local build, SDK/AstrBot use, networking, configuration,
  first-run downloads, upgrades and rollback.

## Executed verification

Environment: Windows x86-64. Application unit suite executed with CPython 3.12.16.

| Check | Result |
| --- | --- |
| `ruff check app scripts tests` | Passed |
| `pytest -q tests/unit` | 68 passed; no skips |
| `python -m compileall -q app scripts tests` | Passed |
| `bash -n scripts/smoke.sh` (Git Bash) | Passed |
| actionlint 1.7.7 against both workflows | Passed |
| YAML parsing of workflows/Compose | Passed |
| Linux CPython 3.12 dependency resolution and hash lock generation | Passed; no CUDA packages |
| Verified upstream archive preparation / revision injection / dictionary cache | Passed on Python 3.12 |
| Python 3.12 frontend imports, local BERT tokenization and mel-filter generation | Passed |
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

The simplified release workflow is statically validated but has not been executed
in this session. It builds and publishes directly without running unit or real
inference tests; manual development verification is separate from publication.

## Image tags and digest

**Published images: none from this session. Immutable digest: unavailable.**

Pushes to `main` and manual dispatch both publish only
`ghcr.io/neozhu/melotts-speech-service:latest`, updating it after a successful build.
No version tag is required. A successful workflow records the immutable digest
in the job summary; publication does not produce inference-test artifacts.

## Manual actions and limitations

1. On Linux, configure `deploy/.env`, build/start with Compose, and run
   `bash scripts/smoke.sh melotts-speech-service:local smoke-results`.
2. Validate 6-GiB memory fit and latency/RTF on an 8-vCPU host with 8 GiB available.
   Hosted runner performance is not evidence for that hardware profile.
   The manual smoke script records the hardware and resource limits used.
3. Configure the `MY_TOKEN` GHCR secret and enable Actions/package write permissions.
   Push to `main` or manually dispatch the workflow. A successful publish is still
   required to satisfy release completion.
4. Make the first GHCR package public if anonymous pulls are desired; deploy the
   published digest from the workflow summary. Keep prior digests for rollback.

First startup requires network access. Offline startup is not a verified mode.
Real-image compatibility is checked manually during development rather than in
the publish workflow. Transformers/tokenizers/fugashi were updated for Python 3.12 wheels;
eager unused-language tokenizer imports add downloads.
Native inference cannot be forcibly cancelled; client timeout retains its occupied
slot until completion. Debian system packages and NLTK dictionary downloads are
resolved at build time despite pinned Python/source/model versions. The `latest`
tag moves on each successful publish; retain verified digests for rollback.
