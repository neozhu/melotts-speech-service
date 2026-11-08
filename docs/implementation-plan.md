# MeloTTS service implementation plan

The engineering spec is the implementation contract. Implement in the current
workspace without committing or publishing changes during development.

1. Add settings, request validation, voice mapping, authentication, error mapping,
   and HTTP contract tests. Keep ML imports out of the unit-test dependency set.
2. Add the official CPU engine adapter with a reusable language registry, verified
   checkpoint downloads, pinned tokenizer/BERT revisions, and WAV/MP3 encoding.
   Warm actual Mandarin audio asynchronously before reporting readiness.
3. Add one bounded inference worker with four waiting slots. Test saturation,
   queued expiry, cancellation, startup failure, and live-health responsiveness.
   Running native inference retains its slot until it finishes.
4. Resolve exact Python 3.12/Linux dependencies; add the non-root Docker image,
   persistent cache volume, read-only Compose deployment, and configuration.
5. Add PR/main development CI and a release pipeline that builds and pushes only
   latest with provenance/SBOM and a recorded digest, without rerunning tests.
   Keep manual real tests for Mandarin, mixed text, every English voice, speed
   extremes, cache restart, overload, and a 100-request soak with latency/RTF output.
6. Run local lint/unit/static checks, review the implementation against SPEC.md,
   and record actual results and environment limitations in the final report.

Design decisions: one FastAPI process; no database or external queue. Downloads
remain lazy and persist under /data/hf. The pinned official MeloTTS source keeps
its inference implementation; a documented installation patch adds immutable
revisions to its otherwise unpinned Hugging Face frontend calls. Its eager
frontend imports require several tokenizer-only assets in addition to ZH/EN.
Only ZH/EN acoustic checkpoints and BERT weights used for inference are loaded.

Review focus: no text/secrets in upstream output or exceptions; no capacity leaks
on cancellation; no readiness before valid non-silent WAV; no repeated tests in
the publish workflow; no undeclared writable paths at runtime.
