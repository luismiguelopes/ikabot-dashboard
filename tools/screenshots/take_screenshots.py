"""Take the README screenshots from a running dashboard, with fictional data.

Every /api/* response is rewritten by anonymize.Anonymizer before the page renders it,
and every request that is not a read is answered locally, so taking screenshots never
changes anything in the bot. Screenshots are only written if no real name leaked.

Usage (from the repository root, dashboard running on port 5001):

    pip install playwright
    playwright install chromium
    python tools/screenshots/take_screenshots.py

The dashboard password is read from DASHBOARD_PASSWORD (environment or .env).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from anonymize import Anonymizer  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# name -> (page id, text of a tab to click or "", viewport height)
SHOTS = {
    "home": ("home", "", 900),
    "targets": ("mundo", "", 900),
    "cities": ("cities", "", 900),
    "transports": ("movements", "Transports", 900),
    "construction": ("construction", "", 900),
    "buildings": ("buildings", "", 900),
}
SEED_ENDPOINTS = ["data", "military", "movements", "world-scan", "farm",
                  "espionage/missions", "espionage/spy-counts", "attack-log", "loot-log",
                  "loot-stats", "transport/wine-buy/status", "building-queue", "activity",
                  "health", "alerts/extra"]
WIDTH = 1440
OUTPUT_WIDTH = 1600   # final image width in pixels (retina-sharp on GitHub)


def dashboard_password():
    pw = os.environ.get("DASHBOARD_PASSWORD", "")
    env = ROOT / ".env"
    if not pw and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("DASHBOARD_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip('"').strip("'")
    return pw


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:5001")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("shots", nargs="*", default=list(SHOTS), help="subset of: " + ", ".join(SHOTS))
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    anon = Anonymizer()
    leaks = {}

    def handle(route, request):
        url = request.url
        if "/api/stream" in url:            # SSE carries no names, only "something changed"
            return route.continue_()
        if request.method != "GET" and not url.endswith("/api/login"):
            return route.fulfill(status=200, json={"ok": True})   # never act on the bot
        resp = route.fetch()
        if "json" not in resp.headers.get("content-type", ""):
            return route.fulfill(response=resp)
        payload = resp.json()
        anon.harvest(payload)
        body = json.dumps(anon.transform(payload), ensure_ascii=False)
        found = anon.leaks(body)
        if found:
            leaks[url] = found
        route.fulfill(response=resp, body=body,
                      headers={**resp.headers, "content-type": "application/json"})

    images = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": WIDTH, "height": 900},
                                  device_scale_factor=OUTPUT_WIDTH / WIDTH)
        password = dashboard_password()
        if password:
            r = ctx.request.post(base + "/api/login", data={"password": password})
            if not r.ok:
                sys.exit("login failed: HTTP %d" % r.status)

        seed = {}
        for ep in SEED_ENDPOINTS:
            r = ctx.request.get(f"{base}/api/{ep}")
            seed[ep] = r.json() if r.ok else None
        anon.seed(seed["data"], seed["military"], seed["movements"],
                  [v for k, v in seed.items() if k not in ("data", "military", "movements")])

        ctx.add_init_script("localStorage.setItem('ikabot_lang','en');")
        ctx.route("**/api/**", handle)
        page = ctx.new_page()
        for name in args.shots:
            tab, click, height = SHOTS[name]
            page.set_viewport_size({"width": WIDTH, "height": height})
            page.add_init_script(f"localStorage.setItem('ikabot_default_tab','{tab}');")
            page.goto(base + "/")
            page.wait_for_timeout(5000)
            if click:
                page.get_by_text(click, exact=True).first.click()
                page.wait_for_timeout(2500)
            images[name] = page.screenshot(type="jpeg", quality=80)
            print("took", name)
        browser.close()

    if leaks:
        for url, names in leaks.items():
            print(f"LEAK in {url}: {len(names)} real name(s)", file=sys.stderr)
        sys.exit("nothing written: real names would have been visible")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in images.items():
        (out / f"{name}.jpg").write_bytes(data)
    print(f"wrote {len(images)} screenshot(s) to {out}")
    print("Look at every image before committing it.")


if __name__ == "__main__":
    main()
