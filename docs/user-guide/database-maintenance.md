# Database Maintenance & Tools

As an authoritative archive accumulates millions of posts, stories, and media records, maintaining PostgreSQL performance and monitoring disk health is essential.

UltimaScraper provides interactive database tools directly within the WebUI.

---

## Interactive Database Inspection (`DatabaseInspectionModal`)

Open **Tools → Database Inspection** to inspect table sizes and storage consumption:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Table Name           Estimated Rows    Table Size    Index Size  Total │
├────────────────────────────────────────────────────────────────────────┤
│ `media_items`        1,420,500         340 MB        180 MB      520 MB│
│ `posts`              890,200           210 MB        115 MB      325 MB│
│ `execution_ledger`   450,000           120 MB         75 MB      195 MB│
│ `write_receipts`     15,000              8 MB          4 MB       12 MB│
│ `subscriptions`       2,400              2 MB          1 MB        3 MB│
└────────────────────────────────────────────────────────────────────────┘
```

- **Fast Statistical Estimates**: For multi-million row tables, the inspector queries PostgreSQL statistics (`pg_class.reltuples`) to provide instant row counts without locking large tables.
- **Index Overhead Tracking**: Identifies when index bloat exceeds table data sizes, signaling the need for re-indexing or VACUUM operations.

---

## PostgreSQL VACUUM Modal (`DatabaseVacuumModal`)

High-frequency scraping and write-queue operations create significant row churn. The WebUI includes a dedicated maintenance modal (**Tools → Run Database VACUUM**):

### Available Operations

| Operation | Mode | Impact & Usage |
|---|---|---|
| **VACUUM** | Standard | Reclaims storage occupied by dead row versions (tuples) without locking tables. Safe to run while scraping jobs are active. |
| **VACUUM ANALYZE** | Recommended | Reclaims dead space and simultaneously updates optimizer query planning statistics for faster UI search and sorting. |
| **VACUUM FULL** | Exclusive Lock | Aggressively rewrites table files on disk to return free space to the operating system. **Requires exclusive locks**; run only when scrapers are paused. |

---

## Storage Drive Management

Navigate to **Settings → Storage Drives** to configure storage targets:

- **Drive Discovery**: Displays all local physical drives, ZFS datasets, and network mounts (NFS/SMB) attached to the backend host.
- **Threshold Warnings**: Set free-space safety margins (e.g. alert when available storage drops below 10%).
- **Multi-Drive Allocation**: Configure secondary overflow drives when the primary volume nears capacity.
