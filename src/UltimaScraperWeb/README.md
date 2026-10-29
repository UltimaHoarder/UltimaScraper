# UltimaScraperWeb

Holds the React WebUI (`webui/`) and the server that serves it and connects it
to UltimaScraper backends (`ultima_webui_server/`).

- `/` is the WebUI. `/webui/api/v1/*` is this server's own API: sign-in and the
  list of backend connections.
- `/b/{connection}/api/*` and `/b/{connection}/ws/*` proxy to one backend. The
  backend's admin token is added here and never reaches the browser.
- `/api/*` and `/ws/*` proxy to the default connection, so the WebUI works the
  way it did when nginx served it.

The first browser on this server's own network sets the sign-in password. From
anywhere else, the setup code printed in the log is needed as well.

`GET /webui/api/v1/clusters` asks each backend for `/api/v1/system/identity`
and groups the connections by cluster id. Each cluster lists live members that
have no connection yet (from a member's `/api/v1/system/backends`) and backend
ids reported by more than one running backend. The last identity is kept, so an
unreachable backend stays in its cluster.

Native plugin code from a backend runs only when that connection is trusted
(`PUT /webui/api/v1/connections/{id}/plugin-trust`). The default connection
starts trusted, others untrusted. Proxied responses carry
`Content-Security-Policy: sandbox`, so none of them can run as this origin when
opened as a page.

Settings come from the environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `USR_WEBUI_HOST` / `USR_WEBUI_PORT` | `127.0.0.1` / `21120` | Listen address |
| `USR_WEBUI_DATA_DIR` | the user data directory | Connections, sessions and the encryption key |
| `USR_WEBUI_STATIC_DIR` | the bundled WebUI build | Where `index.html` and `assets/` are |
| `USR_WEBUI_SECRET_KEY` (`_FILE`) | generated into the data directory | Encrypts stored backend tokens |
| `USR_WEBUI_DEFAULT_BACKEND_URL` | none | The default connection, e.g. `http://backend:21121` |
| `USR_WEBUI_DEFAULT_BACKEND_TOKEN` (`_FILE`) | none | That backend's admin token |

Run it with `ultimascraper-webui` or `python -m ultima_webui_server`.

`main.py` runs it next to a native backend through `ultima_webui_server.launcher`,
which also starts the Vite dev server in a source checkout. The launcher imports
only the standard library and `ultima_scraper_core`; the server runs in its own
process.
