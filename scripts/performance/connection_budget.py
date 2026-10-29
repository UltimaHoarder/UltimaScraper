"""Audit retained SQL clients across an explicitly enumerated deployment.

Input describes engine owners, not measured server connections. Include every
backend/container, standby writer and site engine that can be initialized.
NullPool has no retained clients; its in-flight demand needs separate headroom.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def calculate(document):
    rows, identities = [], set()
    for backend in document["backends"]:
        identity = backend["id"]
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("Backend IDs must be nonempty and unique")
        identities.add(identity)
        for owner in backend["owners"]:
            count = integer(owner["processes"], "processes", 1)
            role = owner["role"]
            if role not in {"application", "worker_reader", "writer", "advisory_lock"}:
                raise ValueError("Unsupported engine owner role")
            engines = integer(owner.get("engines_per_process", 1), "engines", 1)
            mode = owner.get("pool_mode", "unknown")
            if mode not in {"unknown", "session", "transaction", "direct"}:
                raise ValueError("Unrecognized effective pool mode")
            size = integer(owner.get("pool_size", 2), "pool_size", 1)
            overflow = integer(owner.get("max_overflow", 0), "max_overflow")
            if role in {"writer", "advisory_lock"}:
                if overflow:
                    raise ValueError("Writer and dedicated lock allocations cannot overflow")
                retained = count * engines * size
            elif (
                mode in {"unknown", "session"}
                or (owner.get("site_reader", False) and mode != "direct")
                or (role == "worker_reader" and mode == "direct")
            ):
                retained = 0
                overflow = 0
            else:
                retained = count * engines * size
            if role == "advisory_lock" and mode == "transaction":
                raise ValueError("Session advisory locks require a dedicated session/direct endpoint")
            rows.append({
                "backend": identity, "owner": owner["name"], "role": role,
                "processes": count, "engines_per_process": engines,
                "pool_mode": mode, "retained_allocation": retained,
                "overflow_allocation": count * engines * overflow,
                "transient_nullpool_demand_excluded": retained == 0,
            })
    reserved = integer(document.get("reserved_connections", 0), "reserved_connections")
    total = sum(row["retained_allocation"] + row["overflow_allocation"] for row in rows) + reserved
    limit = document.get("allocation_limit")
    if limit is not None:
        integer(limit, "allocation_limit", 1)
    return {
        "scope": "Configured client allocations, not measured PostgreSQL server connections or a bound on NullPool in-flight clients",
        "backends": len(identities), "owners": rows,
        "reserved_connections": reserved, "allocated_clients": total,
        "allocation_limit": limit,
        "within_allocation_limit": None if limit is None else total <= limit,
        "requires_transient_and_operational_headroom": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    result = calculate(json.loads(args.inventory.read_text()))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["within_allocation_limit"] is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
