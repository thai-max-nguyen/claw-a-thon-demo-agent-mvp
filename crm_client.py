"""Full-auto CRM client for the Growth Assistant bot.

The bot stages noti as DRAFT in the Zalopay CRM tool WITHOUT any manual token:
it reads its own office.zalopay.vn session straight from the local Arc cookie
store (Chromium AES-GCM/CBC cookies, key from the macOS Keychain), exactly like
the browser would. No copy-as-cURL, no pasted JWT — the bot authenticates as the
logged-in operator on this machine.

Safety: every write sets status=INACTIVE (DRAFT). The agent proposes; a human
publishes. If the local session is dead, raises CrmSessionError with a one-line
fix so the bot can tell the operator to refocus the CRM tab.
"""
import os
import json
import shutil
import sqlite3
import hashlib
import tempfile
import subprocess
import urllib.request
import urllib.error
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CRM_API = "https://office.zalopay.vn/ge/crm/platform/api"
COOKIES_DB = os.path.expanduser("~/Library/Application Support/Arc/User Data/Default/Cookies")
CRM_LINK = "https://office.zalopay.vn/ge/crm/tool/asset-management/notifications"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

# action identity -> existing DRAFT noti id (idempotent updates, no proliferation)
NOTI_IDS = {"Grab": 16550, "_ACQ": 16559, "XANH SM": 16560, "Be": 16561}
MBS_LABEL = {"id": "CRM-label-9159280a-71fd-4dfd-bdd5-0333e1184b38", "name": "[MBS] Mobility Services"}
# Acquisition is cross-merchant -> default its CTA to Grab (dominant first-ride channel)
GRAB_ZPA, GRAB_ZPI = "zalopay://launch/app/2222", "https://grb.to/Homepage"


class CrmSessionError(RuntimeError):
    pass


def _safe_storage_key():
    r = subprocess.run(["security", "find-generic-password", "-s", "Arc Safe Storage", "-w"],
                       capture_output=True, text=True)
    pw = (r.stdout or "").strip().encode()
    if not pw:
        raise CrmSessionError("can't read Arc Safe Storage key from Keychain (allow access once)")
    return hashlib.pbkdf2_hmac("sha1", pw, b"saltysalt", 1003, 16)


def _cookie_header():
    """Decrypt the office.zalopay.vn session (+ analytics cookies the gateway expects)
    from the live Arc cookie store and return a ready Cookie header string."""
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy(COOKIES_DB, tmp)
    key = _safe_storage_key()
    con = sqlite3.connect(tmp)

    def dec(blob):
        d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        pt = d.update(blob[3:]) + d.finalize()
        pt = pt[:-pt[-1]]
        for cand in (pt, pt[32:]):
            try:
                s = cand.decode("utf-8")
                if s.isprintable():
                    return s
            except Exception:
                pass
        return ""

    ck = {}
    try:
        for name, blob in con.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%zalopay%' "
            "AND (host_key='office.zalopay.vn' OR name LIKE '\\_%' ESCAPE '\\')"):
            ck[name] = dec(blob)
    finally:
        con.close()
        try:
            os.remove(tmp)
        except OSError:
            pass
    if not ck.get("backoffice_token"):
        raise CrmSessionError("no office.zalopay.vn session in Arc — open the CRM tool tab once")
    return "; ".join(f"{k}={v}" for k, v in ck.items() if v)


def _headers(cookie):
    return {"Cookie": cookie, "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*", "Origin": "https://office.zalopay.vn",
            "User-Agent": UA, "Referer": CRM_LINK,
            "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"}


def _get_json(url, headers):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25)
    if "json" not in (r.headers.get("content-type") or ""):
        raise CrmSessionError("CRM session expired — click into the CRM tab once, then retry")
    return json.loads(r.read())


def _content_for(action):
    """Resolve the noti content to embed (variant B — no dynamic param) + deeplinks."""
    n = action.get("noti") or {}
    var = n.get("variant_b") or n.get("variant_a") or {}
    merchant = action.get("merchant")
    zpa = n.get("zpa_redirection") if merchant else GRAB_ZPA
    zpi = n.get("zpi_redirection") if merchant else GRAB_ZPI
    if not zpa or "see deeplink" in str(zpa):
        zpa, zpi = GRAB_ZPA, GRAB_ZPI
    return {"name": action.get("noti_name") or action["segment"]["name"],
            "title": var.get("title", ""), "body": var.get("body", ""), "zpa": zpa, "zpi": zpi}


def stage_drafts(actions):
    """Stage each action as a DRAFT noti in CRM (idempotent update of the MBS slots).
    Returns a list of {id, name, title, body, zpa, zpi} — the exact content embedded."""
    cookie = _cookie_header()
    h = _headers(cookie)
    out = []
    for a in actions:
        nid = NOTI_IDS.get(a.get("merchant") or "_ACQ")
        if not nid:
            continue
        c = _content_for(a)
        o = _get_json(f"{CRM_API}/notifications/{nid}", h)
        d = o.get("data", o)
        d.update({
            "name": c["name"], "notificationName": c["name"], "status": "INACTIVE",
            "type": "Promotion", "labels": [MBS_LABEL], "contentLabels": [MBS_LABEL],
            "notificationTitle": c["title"], "outAppDescription": c["body"], "inAppDescription": c["body"],
            "zpaClickDestinationLink": c["zpa"], "zpaClickDestinationType": "OPEN_WEB",
            "zpiClickDestinationLink": c["zpi"], "zpiClickDestinationType": "OPEN_WEB",
            "buttonName1st": "Đặt ngay!", "buttonActionType1st": "OPEN_WEB",
            "buttonLink1st": c["zpa"], "enableButton1st": True,
        })
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{CRM_API}/notifications/{nid}", data=json.dumps(d, ensure_ascii=False).encode(),
                method="PUT", headers=h), timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302):
                raise CrmSessionError("CRM session expired mid-write — refocus the CRM tab, retry")
            raise
        out.append({"id": nid, **c})
    return out
