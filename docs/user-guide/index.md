# Operator User Guide

Welcome to the **UltimaScraper Operator User Guide**. This guide walks through using the React WebUI to manage platform accounts, monitor distributed scraping jobs, browse and decrypt media libraries, manage performer subscriptions, and maintain database performance.

---

## Guide Overview

```
├── WebUI & Multi-Backend       — Layout, navigation, backend switcher, and cluster failover
├── Profiles & Authentications  — Session credentials, cookies, guest pools, and profile metadata
├── Job Execution & Telemetry   — Submitting scrape tasks, live metrics, and diagnostics reports
├── Content & Media Explorer    — Browsing posts, stories, messages, and Widevine DRM decryption
├── Multi-Performer Streaming   — High-throughput MPS tools, discovery boundaries, and worker pools
└── Database Maintenance       — Interactive table inspection, PostgreSQL VACUUM, and row audits
```

---

## Core Operator Concepts

| Concept | Purpose | Where to Find It |
|---|---|---|
| **Backends** | Independent UltimaScraper API servers managing local workers and storage. | Header dropdown / Manage Backends |
| **Clusters** | Multiple backends sharing a single PostgreSQL database for coordinated work. | Header dropdown / System Fleet |
| **Authentications** | Account session credentials (OnlyFans, Fansly, LoyalFans). | Settings → Authentications |
| **Performer Profiles** | Scraped creators with timeline posts, message histories, and media assets. | Profiles / Users directory |
| **Jobs & Tasks** | Batched scrape and download execution units dispatched across Redis workers. | Jobs navigation tab |
| **Content Library** | Unified media browser supporting image previews, video streams, and audio. | Content / Media view |
| **MPS (Multi-Performer)** | Mass parallel scraping pipeline designed for large multi-account workloads. | Tools → MPS Tool |

---

## Recommended Next Steps

- Learn how to navigate between multiple servers in **[WebUI & Multi-Backend Management](webui-overview.md)**.
- Connect your first platform credentials in **[Profiles & Authentications](accounts-profiles.md)**.
- Queue and monitor your first scrape in **[Job Execution & Telemetry](job-management.md)**.
