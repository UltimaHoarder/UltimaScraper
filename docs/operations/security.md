# Security Model & Hardening

UltimaScraper enforces strict boundaries to protect stored credentials, scraper authentication sessions, and database state across both single-host and multi-tenant deployments.

---

## Authentication & Access Control

### 1. WebUI Server Access
- **Single Master Password**: Access to the WebUI server is guarded by an operator password.
- **First-Time Password Initialization**:
  - The first browser connecting from a loopback (`127.0.0.1`) or private network IP (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) may set the password directly.
  - Remote connections, and every connection through a reverse proxy that is not listed in `USR_WEBUI_TRUSTED_PROXIES`, must supply the ephemeral **Setup Code** printed in the WebUI container logs on first startup.
  - The password must be at least 12 characters. Changing it signs out every other browser.
- **Host Names**: The WebUI answers only to IP addresses, single-label names, this machine's own names, private names such as `*.local`, `*.lan` and `*.home.arpa`, and the names in `USR_WEBUI_ALLOWED_HOSTS`. This stops DNS rebinding, where a public site points its own name at your server. See [Host names and reverse proxies](webui-server.md#host-names-and-reverse-proxies).
- **Response Headers**: Pages cannot be framed by other sites (`frame-ancestors 'none'`), and responses carry `nosniff` and a same-origin referrer policy.
- **Session Tokens**: Handled exclusively via `HttpOnly`, `SameSite=Strict`, secure cookies with automatic CSRF origin validation.
- **Brute-Force Protection**: Failed sign-in attempts are progressively rate-limited by IP address.

### 2. Backend Admin Tokens
- Every backend instance requires an administrative bearer token.
- Backends reject unauthenticated traffic.
- Tokens are automatically generated at bootstrap and persisted in the protected config volume, or can be specified explicitly via `USR_ADMIN_TOKEN`.

---

## At-Rest Secret Encryption (AES-GCM)

All platform session cookies, authentication tokens, and remote SSH forwarding keys are encrypted at rest using authenticated **AES-256-GCM**:

- The encryption key is derived from a local secret generated in the data volume or provided explicitly via:
  ```env
  USR_WEBUI_SECRET_KEY=base64_encoded_32_byte_key
  ```
- **Key Separation**: Losing the encryption key makes stored platform sessions unreadable. Always back up your config volume alongside your database.

---

## Plugin Sandboxing & Trust Boundaries

UltimaScraper supports modular UI and scraper plugins. To prevent untrusted plugins from compromising credentials:

- **Untrusted by Default**: Backends added from outside the primary stack are treated as untrusted. Their UI components run inside sandboxed frames with restricted capabilities (`Content-Security-Policy: sandbox`).
- **Explicit Trust Grant**: Native UI execution in the top-level application context requires explicitly toggling **Trust native plugins from this backend** in the connection settings.
- **Header Isolation**: Proxied backend HTTP responses carry strict security headers:
  ```http
  Content-Security-Policy: sandbox
  X-Content-Type-Options: nosniff
  ```

---

## Container Hardening

All release containers are configured with least-privilege defaults:
- **Non-Root Execution**: Backend, Worker, and WebUI processes execute as non-root system users (`uid 1000`).
- **No Source Code Dependencies**: Production images contain built wheels and standalone distributions without editable repository bind mounts.
- **Port Exposure**: PostgreSQL and Redis are bound to private container networks and are not mapped to external host interfaces by default.
