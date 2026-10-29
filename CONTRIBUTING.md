# Contributing to UltimaScraper

Thanks for helping out! Bug reports, fixes, docs and new ideas are all welcome.

## Before you start

- **Bugs:** open an issue with the bug template. Say which version you run and
  how you installed it.
- **Features and bigger changes:** open an issue first, so we can agree on the
  approach before you write the code.
- **Security problems:** don't open an issue. Follow [SECURITY.md](SECURITY.md).

Never paste cookies, tokens, passwords, admin tokens or private content into an
issue, a pull request or a log excerpt.

## Setting up

The [native development guide](docs/getting-started/native-development.md)
covers the prerequisites (Python 3.14, `uv`, Node.js, PostgreSQL with pgvector
and Redis). In short:

```bash
git clone https://github.com/UltimaHoarder/UltimaScraper.git
cd UltimaScraper
uv sync --python 3.14 --group dev --group docs
npm --prefix src/UltimaScraperWeb/webui ci
```

UltimaScraper is built from several repositories. This one holds the WebUI, the
WebUI server and the app that runs them. The others are published on PyPI:

| Package | Repository |
|---|---|
| `ultima-scraper-core` | [UltimaHoarder/UltimaScraperCore](https://github.com/UltimaHoarder/UltimaScraperCore) |
| `ultima-scraper-backend` | [UltimaHoarder/UltimaScraperBackend](https://github.com/UltimaHoarder/UltimaScraperBackend) |
| `ultima-scraper-api` | [UltimaHoarder/UltimaScraperAPI](https://github.com/UltimaHoarder/UltimaScraperAPI) |
| `ultima-scraper-db` | [DATAHOARDERS/UltimaScraperDB](https://github.com/DATAHOARDERS/UltimaScraperDB) |
| `ultima-scraper-db-archive` | [UltimaHoarder/UltimaScraperDBArchive](https://github.com/UltimaHoarder/UltimaScraperDBArchive) |

To work on one of them alongside this repository, clone it next to this one and
install it over the published version, for example `uv pip install -e ../UltimaScraperBackend`
(the next `uv sync` puts the published version back). A change to one of them goes in a
pull request to that repository.

## Running the checks

```bash
# Python
uv run pytest -q

# WebUI (in src/UltimaScraperWeb/webui)
npm run lint
npm run typecheck:tests
npm run test:unit
npm run build:production
npm run test:smoke      # Playwright; run `npx playwright install chromium` once

# Docs
uv run zensical build --strict
```

`./scripts/release/check.sh` runs all of these. Pull requests run them on
GitHub Actions too.

## Pull requests

- Keep each pull request to one change, and explain what it does and why.
- Add or update tests for what you change.
- Match the code around your change: its naming, comments and style.
- Update the docs when behaviour or settings change.
- Use made-up values in tests, fixtures and docs: `192.0.2.x` addresses,
  `example.test` names, `/mnt/media`-style paths and obviously fake tokens.
  Never real accounts, cookies, paths or hostnames.
- UI changes: include a screenshot. `npm run screenshots` recaptures the
  README and docs images from demo data.

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).

## Code of conduct

Everyone taking part follows our [Code of Conduct](CODE_OF_CONDUCT.md).
