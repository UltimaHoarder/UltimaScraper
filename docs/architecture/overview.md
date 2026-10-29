# System Architecture Overview

UltimaScraper is architected as an event-driven, distributed scraping and archival control plane. It decouples high-bandwidth network scraping from persistent database writes to ensure maximum throughput and stability.

---

## Architectural Topology

```mermaid
graph TD
    subgraph Client_Layer["Operator Client"]
        Browser["React 19 WebUI (SPA)"]
    end

    subgraph Gateway_Layer["Gateway & Ingress"]
        WebUIServer["WebUI Server\n(ultima_webui_server)\n:21120"]
    end

    subgraph Control_Layer["Control Plane"]
        FastAPI["FastAPI Control Service\n:8000"]
        WS["WebSocket Event Hub"]
    end

    subgraph Coordination_Layer["Coordination & Queuing (Redis)"]
        TaskStream[("Task Queue Stream")]
        WriteBuffer[("Write Queue Stream")]
        PubSub[("Telemetry Pub/Sub")]
        LockManager[("Distributed Leases")]
    end

    subgraph Worker_Layer["Execution & Ingestion"]
        WorkerPool["Worker Pool\n(Scrape & Download)"]
        LeasedWriter["Leased Database Writer\n(Batching & Deduplication)"]
    end

    subgraph Storage_Layer["Authoritative Storage"]
        PostgreSQL[("PostgreSQL 16\n(Ledger, Accounts, Media)")]
        MediaStorage[("Media Target Directory\n(Local Disk, NFS, SMB)")]
    end

    Browser -->|HTTP & WebSocket| WebUIServer
    WebUIServer -->|Proxies with Admin Token| FastAPI
    WebUIServer -->|Proxies Events| WS

    FastAPI -->|Enqueue Jobs| TaskStream
    FastAPI -->|Query State| PostgreSQL
    WS -.->|Subscribes| PubSub

    WorkerPool -->|Pulls Tasks| TaskStream
    WorkerPool -->|Streams Files| MediaStorage
    WorkerPool -->|Pushes Receipts| WriteBuffer
    WorkerPool -->|Publishes Progress| PubSub

    LockManager -.->|Elects| LeasedWriter
    LeasedWriter -->|Drains Batch| WriteBuffer
    LeasedWriter -->|Multi-Row Transaction| PostgreSQL
```

---

## Lifecycle of a Scrape Job

The execution of a scrape workflow follows a multi-stage pipeline:

```mermaid
sequenceDiagram
    autonumber
    actor Operator
    participant WebUI as WebUI Server
    participant API as FastAPI Backend
    participant Redis as Redis Queues
    participant Worker as Worker Pool
    participant Storage as File Storage
    participant Writer as Leased DB Writer
    participant PG as PostgreSQL 16

    Operator->>WebUI: Click "Queue Scrape"
    WebUI->>API: POST /api/v1/jobs/submit
    API->>PG: Record Job in Execution Ledger (PENDING)
    API->>Redis: Enqueue Tasks into Task Stream
    API-->>WebUI: Job ID & Status Confirmation

    loop Task Execution
        Worker->>Redis: Claim Task Batch (XREADGROUP)
        Worker->>Storage: Stream & Verify Media Bytes
        Worker->>Redis: Enqueue Write Receipt
        Worker->>Redis: Publish Telemetry Event
        Redis-->>WebUI: Live Progress Update (WebSocket)
    end

    Writer->>Redis: Drain Write Queue Batch
    Writer->>PG: Commit Bulk Upsert Transaction
    PG-->>Writer: Tx Acknowledged
    Writer->>Redis: Ack Messages (XACK)
```

---

## Subsystem Responsibilities

### 1. WebUI Server (`ultima_webui_server`)
- Authenticates operators using HTTP-only session cookies.
- Proxies requests to local or remote backends, injecting admin bearer tokens.
- Manages SSH tunnels and provides single-click remote backend deployments.

### 2. FastAPI Control Service
- Publishes OpenAPI specifications at `/docs` and `/openapi.json`.
- Dispatches scrape tasks to Redis streams based on job schedules and profile priorities.
- Coordinates worker scaling and health heartbeats.

### 3. Redis Queue & Event Broker
- Acts as a high-speed buffer preventing slow disk writes from throttling fast network scraping.
- Broadcasts real-time download velocities, worker counts, and errors to browser clients.

### 4. Leased Database Writer
- Consolidates writes into efficient batch transactions.
- Provides automatic deduplication, retry exponential backoff, and dead-letter handling.

### 5. PostgreSQL Authoritative Storage
- Maintains immutable audit trails of all scraped posts, messages, stories, and media items.
- Preserves referential integrity across performers, subscriptions, and download paths.
