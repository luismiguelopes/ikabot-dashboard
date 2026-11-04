#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Container healthcheck for the ikabot worker.

Exit 0 = healthy, 1 = unhealthy (autoheal then restarts the container).

The bot is unhealthy when its heartbeat (last_alive.json, refreshed every loop) is older
than BOT_OFFLINE_SECS. BUT a stale heartbeat is NOT always the worker's fault: when the
Docker host (e.g. a laptop) sleeps, the whole container freezes — the worker AND this very
healthcheck stop running — and resumes in the morning with a heartbeat that looks hours old.
Restarting then is pointless (it only drops any `docker attach`) because the worker recovers
on its own within a loop or two once the host is awake.

We tell the two apart with a freeze sentinel: this check stamps its own run time on every
invocation. If more than FREEZE_GAP_SECS elapsed since the previous run, far more than the
healthcheck interval, the host was frozen between runs — so we pass this round (grace) and
let the worker catch up. A genuine hang while the host is AWAKE keeps this check running on
its normal cadence (small gaps), so the staleness test still fires and the container is
restarted as before.
"""
import json
import os
import sys
import time

LOGS_DIR = "/tmp/ikalogs"
LAST_ALIVE = os.path.join(LOGS_DIR, "last_alive.json")
HC_SENTINEL = os.path.join(LOGS_DIR, ".healthcheck_last")

OFFLINE_SECS = int(os.environ.get("BOT_OFFLINE_SECS", "1800"))
# A gap between consecutive healthcheck runs larger than this means the host was frozen
# (the check itself couldn't run), not that the worker stalled. Must be comfortably above
# the compose `interval` (2m) so normal scheduling jitter never looks like a freeze.
FREEZE_GAP_SECS = int(os.environ.get("HC_FREEZE_GAP_SECS", "300"))

now = time.time()

prev = None
try:
    prev = os.path.getmtime(HC_SENTINEL)
except OSError:
    pass
try:
    with open(HC_SENTINEL, "w") as f:
        f.write(str(int(now)))
except OSError:
    pass

# Host just resumed from a freeze (long gap since our last run) → give the worker a pass.
if prev is not None and (now - prev) > FREEZE_GAP_SECS:
    sys.exit(0)

try:
    with open(LAST_ALIVE) as f:
        last_alive = json.load(f)["lastAlive"]
except Exception:
    # No heartbeat yet (e.g. fresh start before the first loop) — start_period covers this.
    sys.exit(1)

sys.exit(0 if (now - last_alive) < OFFLINE_SECS else 1)
