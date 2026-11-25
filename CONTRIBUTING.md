# Contributing

Thanks for your interest in ikabot-dashboard! Contributions of all sizes are welcome: bug
reports, fixes, translations and new features.

## Language

**Everything in this repository is in English**: issues, pull requests, review comments,
commit messages, code and code comments. This keeps the project open to players on every
server, whatever their language. The dashboard itself is translated (pt/en) through its own
i18n, and more languages are welcome.

## Reporting bugs

Open a [GitHub issue](https://github.com/luismiguelopes/ikabot-dashboard/issues) and include:

- what you expected and what happened instead;
- the relevant excerpt of `bot.log` (and the container logs, if useful);
- your game server and language (e.g. `en`, `pt`, `br`), since the bot parses the game's text.

**Remove personal data before posting**: account email, passwords, cookies, session tokens,
Telegram/Discord webhooks, and anything that identifies your game account if you prefer to
keep it private.

## Pull requests

- **Open an issue first for larger changes** (new features, multi-account support, schema
  changes) so we can agree on the approach before you invest time in it. Small fixes can go
  straight to a PR.
- Keep each PR **small and focused** on one thing.
- Describe *what* changed and *why*, and how you tested it.
- The PR title becomes a line in the release notes, so write it as what changes for the user
  (e.g. "Spy counts are read on the Brazilian server") rather than how the code changed.
- Write commit messages in English, in the imperative mood ("Fix wine buyer price check").

### Before opening a PR

Install the test dependencies with `pip install -r requirements-dev.txt`, and clone the
upstream [ikabot](https://github.com/Ikabot-Collective/ikabot) into `./ikabot` (the tag CI uses
is `IKABOT_REF` in `.github/workflows/ci.yml`). CI runs the same checks on every pull request,
and a PR can only be merged once they pass.

- **Tests pass**: `python -m pytest tests/ -q` (`pytest.ini` already sets the paths).
- **No new lint errors**: run `pyflakes` on the Python modules you touched.
- **Frontend builds**: `cd frontend && npm run build` (this also runs the TypeScript check).
- Add or update tests for the behaviour you change. Parsers should be tested against real
  HTML captures (see `tests/fixtures/`), with personal data removed.

### Rules that must not be broken

- **Anti-detection**: every HTTP request to the game must be preceded by a randomised delay
  (`time.sleep(random.randint(...))`) and must respect the active-hours window. No exceptions.
- **No new game requests without need**: prefer reusing data the bot already collects.
- **Never commit secrets**: `.env`, cookies, session files, databases or logs.

### Game text and other servers

Parts of the bot read the exact text the game server returns (e.g. espionage reports). It has
only been tested on the Portuguese (`pt`) server, so other servers may need parser changes.
When adding support for another language or server, keep the existing behaviour intact and
include a real fixture from that server in the tests.

## AI-assisted contributions

AI-assisted contributions are welcome. **If you used AI tools, state in the PR description
which model(s) were used** (e.g. Claude, GPT, Gemini, with the version if you know it). You
are responsible for every line you submit: review it, understand it and test it as if you had
written it yourself.

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
