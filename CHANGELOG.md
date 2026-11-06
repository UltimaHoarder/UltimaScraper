# Changelog

All notable changes to UltimaScraper are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

A complete rebuild of UltimaScraper as a self-hosted platform you run from your
browser.

### Added

- **WebUI:** a dashboard to queue jobs, browse your library, manage accounts and
  creators, and watch workers, throughput and storage live.
- **Setup wizard:** installs the backend, workers, PostgreSQL and Redis on this
  machine or another one over SSH, and checks each step.
- **Jobs and workers:** parallel downloads across many creators, one-click
  retries, and tasks that go back in the queue when a worker stops.
- **Library:** search captions and messages, filter by creator, type or date,
  and preview photos, videos and audio.
- **Statistics:** account creation, posting activity and recurring patterns,
  per site.
- **Clusters:** several backends and workers on one database, run as one
  cluster, with invites for other WebUIs.
- **Storage:** archives spread over several drives, with free-space warnings.
- **Webhooks and plugins** to react to events and extend UltimaScraper.
- **Docker images** for amd64 and arm64: one full image that runs the backend,
  workers and WebUI, each in its own container, and separate backend, worker
  and WebUI images for those who want one role each. Started on its own with
  no database or Redis settings, the full image runs the WebUI.

### Changed

- **License:** UltimaScraper is now licensed under the GNU Affero General
  Public License v3.0 or later (AGPL-3.0-or-later), in place of the GPL-3.0 of
  earlier versions.

### Security

- The WebUI is protected by a password of at least 12 characters, with
  HttpOnly, SameSite=Strict session cookies and same-origin checks on writes.
- The WebUI answers only to local and configured host names, which stops DNS
  rebinding, and asks for a setup code when first opened from elsewhere or
  through a reverse proxy.
- Saved logins and other secrets are encrypted at rest.

[0.1.0]: https://github.com/UltimaHoarder/UltimaScraper/releases/tag/v0.1.0
