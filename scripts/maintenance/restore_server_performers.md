# Restore duplicate performer folders to the server

The WebUI's **Tools → Server Restore** workspace keeps discovery, selection,
file review, preflight and execution in one saved restoration session. Choose a
configured destination archive and include the source roots you want searched.
Roots disabled for new performer placement are still searched. Unavailable and
excluded roots remain visible in scan coverage.

After planning, the performer browser reports exact inspected file counts and
executable bytes. File categories separate restores, empty-file repairs, verified
duplicates, unverified same-size collisions, conflicts and deliberate retentions.
Hashing is optional; duplicate removal always hashes both copies and requires
matching modification times. Ambiguous destinations and unsupported files block
only their performer. Choosing a destination, preferring a competing source, or
keeping both copies creates a new plan that must be reviewed again. Nonempty
server files are retained.

Preflight checks archive identities, available space, write permissions and the
exact file snapshots. Scrape and download handlers take shared drive-root
reservations; restoration takes exclusive reservations throughout execution and
rechecks readiness after acquiring them. Coordination covers workers using the
same host and user-data lock directory. Other storage hosts and external programs
require the explicit paused-writers acknowledgement.

Reservations prevent new managed writers from starting while current writers
drain. A running operation can be stopped at a safe file boundary; copies already
completed remain journaled and require reconciliation before another apply.

Filesystem work runs in detached local worker processes, with durable requests,
results and journals under the application's `server_restore_reviews` data
directory. An API reload does not terminate those workers. A worker failure can
be reconciled from the progress view: completed destinations are reverified and
copies awaiting source removal become explicit `finish_move` actions in a fresh
plan. Interrupted copies and repair temporary files are retained for review.
Recovery never automatically replays a previously approved plan.

The command-line workflow below remains available.

Run from the UltimaScraper checkout with `.venv/bin/python`.

1. `scripts/maintenance/restore_server_performers.py scan --server /path/to/server_archive --output /tmp/inventory.json`
2. Review `/tmp/inventory.md`. Only performers already present in the server's
   archive roster qualify. All configured drive roots are searched,
   including drives disabled for new performer placement. Missing roots are reported.
3. `scripts/maintenance/restore_server_performers.py plan --inventory /tmp/inventory.json --performer sample_performer --output /tmp/plan.json`
   Repeat `--performer` to select more performers, or use `--all-performers`
   instead to plan every match in the inventory. Planning uses size, mtime,
   ctime and inode snapshots. Same-size, same-mtime destination collisions are
   left unverified as `collision`; other collisions are `conflict`. Add
   `--hash-collisions` to identify exact duplicates with SHA256 and
   `--hash-new-files` to hash new files during planning too. Both options can
   take much longer on slow storage. Apply always verifies moved file contents.
   Add `--remove-duplicates --repair-zero-bytes --cleanup-empty` to include
   hash-verified duplicate removal, direct zero-byte server-file replacement
   without backups, and removal of reviewed source directories only when empty.
4. Review `/tmp/plan.md` and its JSON snapshots. Only approved `move`, `remove_duplicate`, and `repair_zero_byte` entries execute.
   Same-content files with different modification timestamps are conflicts.
   Unverified collisions, nonempty conflicts, and competing source files remain untouched.
5. Pause jobs and other writers affecting these folders for the entire move.
   After approval, compute `sha256sum /tmp/plan.json` and run:
   `scripts/maintenance/restore_server_performers.py apply --plan /tmp/plan.json --journal /tmp/move-journal.jsonl --approved-plan-sha256 CHECKSUM`

Each command must be prefixed with `.venv/bin/python`. Reports and journals
require new filenames, so earlier reviews cannot be silently overwritten.

Apply validates the full snapshot first, hashes the source before copying,
then copies exclusively, flushes,
preserves metadata with `copystat`, verifies SHA256/size/mtime, journals the
verified copy, and removes the source. Source snapshots preserve nanosecond
modification times; verified destinations may round within the same whole second.
Larger timestamp changes retain the source and stop that performer's execution.
Existing server directories retain their times;
new directories inherit source times. Empty source directories are retained unless cleanup is included in the approved plan.
The journal records completed copies and removals; execution is not an atomic
transaction and stops on failure. Re-scan and re-plan before retrying a partial
run; do not replay a stale plan.

Symlinks and special files are refused. Filesystem permissions and extended
attributes are copied as supported by `copystat`; ownership, creation/birth time,
ctime, hardlink relationships, and filesystem-specific ACLs are not guaranteed.
Hashing may update access times. No application database paths are rewritten.
Conflicts and redundant copies need a separately reviewed cleanup decision.
