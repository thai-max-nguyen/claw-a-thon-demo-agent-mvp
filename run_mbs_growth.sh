#!/bin/zsh
# Daily MBS Growth report -> Telegram group + the Business Owner's Confluence page.
# Dashboard-only (no Excel). Needs a live Atlas SSO session in Chrome at run time;
# if the session is dead or the audit fails, mbs_growth.py aborts without sending.
cd /Users/lap15964/clawathon-demo/claw-a-thon-demo-agent || exit 1
set -a
[ -f .env ] && source .env   # provides TELEGRAM_BOT_TOKEN + TELEGRAM_GROUP_ID (gitignored)
set +a
echo "===== run $(date '+%Y-%m-%d %H:%M:%S') ====="
# self-heal the Atlas session first: opens Chrome + auto-clicks VNG SSO (no creds;
# inherits the VNG session). If VNG SSO itself is expired, mbs_growth aborts safely.
/usr/bin/python3 /Users/lap15964/.config/life-ops/atlas_auto_login.py 2>&1 | tail -3 || true
exec ./venv/bin/python3 mbs_growth.py --all
