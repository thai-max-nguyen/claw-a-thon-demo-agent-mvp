"""CRM tool API probe (READ-ONLY) — maps the segment/noti endpoints for the
confirm-gated noti feature. Needs a live bearer token (in-memory sessionStorage
on office.zalopay.vn) passed via env CRM_TOKEN — never persisted.

Usage:
    CRM_TOKEN='eyJ...' python3 crm_probe.py

What it does (no writes):
  * GET the segments list endpoint -> confirms read access + shows shape
  * probes likely create/noti sibling endpoints with OPTIONS/GET to learn the
    surface (does NOT POST — creation only happens later, behind the Telegram
    confirm-gate, with an explicit dry-run preview)
"""
import json
import os
import ssl
import urllib.request

BASE = "https://office.zalopay.vn/api/crm/tool"
TOKEN = os.getenv("CRM_TOKEN", "").strip()
CTX = ssl.create_default_context()


def call(path, method="GET", body=None):
    url = BASE + path
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if TOKEN:
        headers["Authorization"] = TOKEN if TOKEN.lower().startswith("bearer") else f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=25, context=CTX)
        return r.status, r.headers.get("Content-Type", ""), r.read(2000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(800).decode("utf-8", errors="replace")
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"


def main():
    if not TOKEN:
        print("No CRM_TOKEN set — paste the bearer token and run with CRM_TOKEN='...'")
        return
    print("=== READ: segments list ===")
    for path in ["/user-profile/segments?page=0&size=10",
                 "/user-profile/segments",
                 "/user-profile/segment?page=0&size=10"]:
        st, ct, body = call(path)
        print(f"GET {path}\n  {st} {ct[:30]}\n  {body[:400]}\n")
        if st == 200 and "json" in ct:
            break
    print("=== SURFACE probe (read-only, no POST) ===")
    for path in ["/user-profile/segments/conditions", "/notification", "/notification/templates",
                 "/user-profile/segments/app", "/app-id"]:
        st, ct, body = call(path)
        print(f"GET {path} -> {st} {ct[:24]} {body[:120]}")


if __name__ == "__main__":
    main()
