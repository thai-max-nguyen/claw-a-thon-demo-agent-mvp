# GreenNode AgentBase — runtime never schedules (CREATING → ERROR, empty logs)

**To:** support@greennode.ai (cc Claw-a-thon organizers) · **Hotline:** 1900 1549
**Account:** claw26-team41@vngcloud.vn · **Region:** HCM · **Date:** 2026-06-16

## Problem
Every Custom Agent runtime we create is accepted (HTTP 200, status CREATING) but **never starts**: it sits ~11 minutes with `updatedAt` frozen at creation, **logs stay empty** (no container ever runs), then flips to **ERROR** with `statusReason: null`. The runtime logs/events API returns **403**, so we cannot self-diagnose; the portal VIEW DETAIL logs are also empty.

## We exhausted every variable on our side (6 deploys)
| Variable | Tried | Result |
|---|---|---|
| Flavor | `runtime-s2-general-2x4` (×4), `runtime-s2-general-4x8` (×1) | all ERROR ~11 min |
| Image | `:v1` (buildx multi-arch index), `:v2` (clean single linux/amd64 manifest) | both ERROR |
| Image health | `linux/amd64` (matches platform); runs locally → container `Up (healthy)`, `GET /health` → 200 on `0.0.0.0:8080`; `docker pull` with the registry-credential creds succeeds | image is fine |
| Create body | `port: 8080`, `imageAuth` from `/cr/api/v1/registry-credential`, `autoscaling.cpuUtilization/memoryUtilization`, `networkConfig.mode=PUBLIC` | config is fine |
| Credits | ~4.3M available | not a quota issue |

**Empty logs = the container image is never even pulled/started — the pod never schedules.** This is upstream of anything in our image or config.

## Asks
1. Why do our runtimes never schedule? (Node/flavor capacity in HCM? image-pull from `vcr.vngcloud.vn` inside the platform? scheduler timeout?)
2. Please expose the runtime **logs/events** API (currently 403) or surface `statusReason` so teams can self-serve.
3. Claw-a-thon deadline is **12:00 17/06** and a live ACTIVE runtime is submission requirement #1 — priority help appreciated.

Image for repro: `vcr.vngcloud.vn/111480-abp111736/growth-assistant:v2` (single linux/amd64, `/health` → 200, port 8080).
