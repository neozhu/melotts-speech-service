#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE=${1:?Usage: bash scripts/smoke.sh IMAGE [REPORT_DIRECTORY]}
REPORT_DIR=${2:-smoke-results}
mkdir -p "$REPORT_DIR"
WORK_DIR=$(mktemp -d)
NAME="melotts-smoke-${GITHUB_RUN_ID:-local}-$$"
MODELS="${NAME}-models"
CACHE="${NAME}-cache"
CPU_LIMIT=$(python -c 'import os; print(min(6, os.cpu_count() or 1))')
export API_KEY
API_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
printf 'API_KEY=%s\n' "$API_KEY" > "$WORK_DIR/environment"
chmod 600 "$WORK_DIR/environment"

cleanup() {
  status=$?
  docker logs "$NAME" > "$REPORT_DIR/container.log" 2>&1 || true
  docker inspect "$NAME" > "$WORK_DIR/inspect.json" 2>/dev/null || true
  # Full docker inspect includes the secret environment. Export only resource/state fields.
  python - "$WORK_DIR/inspect.json" "$REPORT_DIR/container.json" <<'PY'
import json, sys
try:
    container = json.load(open(sys.argv[1]))[0]
    json.dump({"state": container["State"], "memory_limit": container["HostConfig"]["Memory"],
               "nano_cpus": container["HostConfig"]["NanoCpus"],
               "user": container["Config"]["User"], "image_id": container["Image"]},
              open(sys.argv[2], "w"), indent=2)
except (OSError, ValueError, IndexError):
    pass
PY
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$MODELS" "$CACHE" >/dev/null 2>&1 || true
  rm -f "$WORK_DIR/environment" "$WORK_DIR/inspect.json"
  rmdir "$WORK_DIR"
  exit "$status"
}
trap cleanup EXIT
docker volume create "$MODELS" >/dev/null
docker volume create "$CACHE" >/dev/null

start_container() {
  docker run --detach --name "$NAME" --cpus "$CPU_LIMIT" --memory 6g --memory-swap 6g \
    --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
    --tmpfs /tmp:rw,noexec,nosuid,size=512m --env-file "$WORK_DIR/environment" \
    --mount "type=volume,source=$MODELS,target=/data/hf" \
    --mount "type=volume,source=$CACHE,target=/data/cache" \
    --publish 127.0.0.1::8000 "$IMAGE" >/dev/null
  PORT=$(docker port "$NAME" 8000/tcp | sed 's/.*://')
}
start_container
test "$(docker inspect --format '{{.Config.User}}' "$NAME")" = '10001:10001'
docker exec "$NAME" python -c \
  'import torch; assert torch.version.cuda is None; assert not torch.cuda.is_available()'
python tests/integration/verify_service.py --url "http://127.0.0.1:$PORT" \
  --report "$REPORT_DIR/inference.json" --soak 100
test "$(docker inspect --format '{{.State.OOMKilled}}' "$NAME")" = 'false'
test "$(docker inspect --format '{{.State.Running}}' "$NAME")" = 'true'
docker stats --no-stream --format '{{json .}}' "$NAME" > "$REPORT_DIR/resources.json"
docker logs "$NAME" > "$REPORT_DIR/first-start.log" 2>&1
if grep -Fq -- "$API_KEY" "$REPORT_DIR/first-start.log"; then
  echo 'Secret detected in container logs' >&2
  exit 1
fi
if grep -Fq -e '你好，今天的天气很好' -e 'Docker 和 Python 服务正常' \
    -e 'Hello, this is the local English speech service' "$REPORT_DIR/first-start.log"; then
  echo 'Input text detected in container logs' >&2
  exit 1
fi
docker stop --time 300 "$NAME" >/dev/null
docker rm "$NAME" >/dev/null
start_container
python tests/integration/verify_service.py --url "http://127.0.0.1:$PORT" --ready-only
test "$(docker inspect --format '{{.State.OOMKilled}}' "$NAME")" = 'false'
test "$(docker inspect --format '{{.State.Running}}' "$NAME")" = 'true'
echo 'Real inference, decoding, soak and persistent-cache restart passed.'
