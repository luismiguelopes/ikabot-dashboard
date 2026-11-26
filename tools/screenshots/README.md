# README screenshots

`take_screenshots.py` takes the screenshots in `docs/screenshots/` from a running
dashboard, with **fictional data**:

- every `/api/*` response is rewritten by `anonymize.py` before the page renders it:
  - city, player, island and alliance names get stable fictional names;
  - coordinates are shifted;
  - every quantity (resources, gold, ships, citizens, loot, production) is multiplied by one
    random factor, picked on each run and never stored, so ratios such as warehouse fill
    and wine runway stay right;
  - only the first 10 own cities are shown;
  - building, unit, wonder and mission names from the Portuguese server are shown in English;
  - tokens and webhooks are blanked;
- every request that is not a read is answered locally, so the bot is never asked to do
  anything;
- if a real name is still found in any response, nothing is written.

```bash
pip install playwright
playwright install chromium
python tools/screenshots/take_screenshots.py              # all screenshots
python tools/screenshots/take_screenshots.py home cities  # only some
```

The dashboard must be running (default `http://localhost:5001`, change with `--base-url`).
The password is read from `DASHBOARD_PASSWORD` in the environment or in `.env`.

Always look at every image before committing it.
