#!/bin/bash
# Smoke test — boots the agent + checks every endpoint. Passes in stub mode
# (no API key) and in live mode. Exit 0 = all pass.
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8090}"
P="http://127.0.0.1:${PORT}"
FAIL=0

# pick entrypoint
uvicorn app:app --host 127.0.0.1 --port "$PORT" >/tmp/agent_smoke.log 2>&1 &
SV=$!
trap 'kill $SV 2>/dev/null' EXIT
sleep 5

check() { # label expected actual
  if [ "$2" = "$3" ]; then echo "  PASS  $1 ($3)"; else echo "  FAIL  $1 (want $2 got $3)"; FAIL=1; fi
}

check "/health 200"      200 "$(curl -s -o /dev/null -w '%{http_code}' $P/health)"
check "/ root 200"       200 "$(curl -s -o /dev/null -w '%{http_code}' $P/)"
check "/question 200"    200 "$(curl -s -o /dev/null -w '%{http_code}' -X POST $P/question -H 'Content-Type: application/json' -d '{"category":"retention","merchant":"Grab","session_id":"t1"}')"
check "/chat 200"        200 "$(curl -s -o /dev/null -w '%{http_code}' -X POST $P/chat -H 'Content-Type: application/json' -d '{"message":"Why is MPU pacing behind target?","session_id":"t1"}')"
check "/evaluate 200"    200 "$(curl -s -o /dev/null -w '%{http_code}' -X POST $P/evaluate -H 'Content-Type: application/json' -d '{"question":"How to lift NPU?","answer":"Run a first-ride acquisition push to high-intent non-payers.","session_id":"t1"}')"
check "/session 200"     200 "$(curl -s -o /dev/null -w '%{http_code}' $P/session/t1)"
check "bad category 400" 400 "$(curl -s -o /dev/null -w '%{http_code}' -X POST $P/question -H 'Content-Type: application/json' -d '{"category":"nope"}')"
check "empty chat 400"   400 "$(curl -s -o /dev/null -w '%{http_code}' -X POST $P/chat -H 'Content-Type: application/json' -d '{"message":""}')"
check "missing sess 404" 404 "$(curl -s -o /dev/null -w '%{http_code}' $P/session/none)"

[ "$FAIL" = 0 ] && echo "ALL SMOKE TESTS PASSED" || echo "SOME TESTS FAILED"
exit $FAIL
