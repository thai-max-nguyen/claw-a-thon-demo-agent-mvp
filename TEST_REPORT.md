# Local Test Report — claw-a-thon-demo-agent

Date: 2026-06-15
Tester: Claude Code (automated local smoke test)
Target: `/Users/lap15964/clawathon-demo/claw-a-thon-demo-agent`
Result: **PASS** — no code changes required.

## Summary

| Step | Check | Result |
|------|-------|--------|
| 1 | venv + `pip install -r requirements.txt` | PASS |
| 2 | Start `uvicorn app:app` (background) | PASS — startup complete |
| 3 | `GET /health` returns `200` | PASS |
| 4 | `POST /chat` returns JSON (stub, no key) | PASS |
| 5 | Kill server | PASS |

## Step 1 — Install dependencies

Command:
```
python3 -m venv venv
./venv/bin/python -m pip install --quiet --upgrade pip
./venv/bin/python -m pip install --quiet -r requirements.txt
./venv/bin/python -c "import fastapi, uvicorn, pydantic; print('imports ok')"
```

Output:
```
EXIT=0
imports ok
```

requirements.txt contents:
```
fastapi
uvicorn[standard]
openai>=1.40.0
requests
python-dotenv
```
(`pydantic` is pulled in transitively by fastapi — import verified above.)

## Step 2 — Start server (background)

Command:
```
nohup ./venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8080 > /tmp/agent_server.log 2>&1 &
```

Server log (tail):
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

## Step 3 — Health probe

Command:
```
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health
```

Output:
```
200
```

## Step 4 — Chat endpoint (stub mode, no API key)

Command:
```
curl -s -X POST http://127.0.0.1:8080/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Tell me about yourself"}'
```

Output:
```json
{"status":"stub","answer":"[stub — set LLM_API_KEY to enable live model] You asked: Tell me about yourself","model":null}
```

Valid JSON returned. `status:"stub"` is expected behavior when `LLM_API_KEY` is empty — the app degrades gracefully instead of failing.

## Step 5 — Kill server

Command:
```
pkill -f "uvicorn app:app --host 127.0.0.1 --port 8080"
curl -s -o /dev/null --max-time 2 http://127.0.0.1:8080/health   # no response
```

Output:
```
server killed
```

## Conclusion

The agent boots cleanly, `/health` returns 200, and `/chat` returns a well-formed JSON
answer in stub mode without any API key. No bugs found; no fixes applied.

To enable live model answers, set `LLM_API_KEY` (and `LLM_BASE_URL` / `LLM_MODEL`) per
`.env.example` — the chat response will then return `status:"success"` with a model answer.
