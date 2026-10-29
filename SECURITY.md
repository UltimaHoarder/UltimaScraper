# Security

## Reporting a vulnerability

Please report security issues privately through GitHub:
**[Report a vulnerability](https://github.com/UltimaHoarder/UltimaScraper/security/advisories/new)**
(the repository's **Security** tab → **Report a vulnerability**).

Do not open a public issue for a vulnerability. Never include account cookies,
tokens, passwords, admin tokens, encryption keys or private content in a
report: describe the problem and how to reproduce it with test values instead.

We aim to acknowledge a report within a week, and will keep you updated while
we work on a fix. Once a fix is released, we credit reporters who want to be
credited in the advisory.

## Supported versions

Security fixes go into the latest release. Upgrade to it before reporting, if
you can.

## Running UltimaScraper safely

UltimaScraper is a service you run yourself. Treat its admin token, database
credentials, Redis password, saved logins and encryption keys as secrets.

- Do not expose PostgreSQL or Redis publicly.
- Put a WebUI that other machines reach behind TLS, and list its public names
  in `USR_WEBUI_ALLOWED_HOSTS`. See
  [Host names and reverse proxies](docs/operations/webui-server.md#host-names-and-reverse-proxies).
- Keep `USR_SECRET_KEY` stable and backed up. Without it, saved logins can't be
  read.
- Use a long, separate `USR_ADMIN_TOKEN`, and rotate it if it is disclosed.
- Mount only the storage paths UltimaScraper needs.

The [security model](docs/operations/security.md) describes how the WebUI and
backends protect sign-in, sessions and stored secrets.
