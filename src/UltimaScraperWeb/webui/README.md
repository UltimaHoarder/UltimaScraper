# UltimaScraper WebUI

The WebUI is the browser control surface for the UltimaScraper FastAPI
control plane. It uses React, TypeScript, Vite, and npm.

From this directory:

```bash
npm ci
npm run dev
```

The development server proxies `/api` and `/ws` to
`http://127.0.0.1:21121`. Set `USR_ADMIN_TOKEN` for local authenticated
development.

Validation:

```bash
npm run lint
npm run test:unit
npm run build:production
npm run test:smoke
```

Route modules select a theme view; shared behavior belongs under `src/features`,
`src/components`, and `src/api`. Theme directories should contain only
intentional presentation differences.
