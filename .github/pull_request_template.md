## What and why

<!-- What does this PR change, and why? Link the issue if there is one (e.g. "Closes #12"). -->

## How it was tested

<!-- Tests added or updated, and anything you checked by hand (dashboard, live game, logs). -->

## Checklist

- [ ] Small and focused on one thing (larger changes were discussed in an issue first)
- [ ] Tests pass: `python -m pytest tests/ -q`
- [ ] Tests added or updated for the behaviour that changed
- [ ] No new `pyflakes` warnings in the modules I touched
- [ ] Frontend builds (`cd frontend && npm run build`), if the frontend changed
- [ ] Every new request to the game has a randomised delay and respects the active-hours window
- [ ] No secrets or personal data (emails, cookies, tokens, webhooks, real city or player names)
- [ ] Code, comments and commit messages in English

## AI assistance

<!-- If you used AI tools, name the model(s), e.g. "Claude Opus 4.5" or "GPT-5". Otherwise write "None". -->
