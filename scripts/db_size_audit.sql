-- Read-only size audit for ultima_archive. Catalog/statistics views only; no table scans.
-- psql "$ULTIMA_ARCHIVE_DATABASE_URL" -f scripts/db_size_audit.sql > db_size_audit.txt
-- Run after PostgreSQL is accepting connections. No cleanup or DDL is performed.
-- Table totals already include their indexes/TOAST; do not add those columns again.
-- Dead tuples are estimates, not an estimate of filesystem-reclaimable bytes.
-- Zero index scans alone never justify dropping an index, especially after a reset.
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
\pset pager off

\echo '== 0. Database size and measurement context (excludes cluster WAL)'
SELECT clock_timestamp() AS measured_at, current_database() AS database,
       pg_is_in_recovery() AS in_recovery,
       pg_postmaster_start_time() AS server_started,
       pg_database_size(current_database()) AS database_bytes,
       pg_size_pretty(pg_database_size(current_database())) AS database_size,
       stats_reset
FROM pg_stat_database WHERE datname = current_database();

\echo '== 1. Largest tables (heap / indexes / toast)'
SELECT n.nspname || '.' || c.relname AS table,
       c.reltuples::bigint AS est_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
       pg_size_pretty(pg_relation_size(c.oid)) AS heap,
       pg_size_pretty(pg_indexes_size(c.oid)) AS indexes,
       pg_size_pretty(coalesce(pg_total_relation_size(nullif(c.reltoastrelid, 0)), 0)) AS toast
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname !~ '^pg_'
  AND n.nspname <> 'information_schema'
ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 40;

\echo '== 1b. Logical table families, including every physical partition once'
WITH RECURSIVE members(root_oid, member_oid) AS (
    SELECT c.oid, c.oid
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind IN ('r','p','m') AND n.nspname !~ '^pg_'
      AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid=c.oid)
    UNION ALL
    SELECT m.root_oid, i.inhrelid
    FROM members m JOIN pg_inherits i ON i.inhparent=m.member_oid
), totals AS (
    SELECT root_oid,
           count(*) FILTER (WHERE c.relkind IN ('r','m')) AS physical_tables,
           sum(CASE WHEN c.relkind IN ('r','m')
                    THEN pg_total_relation_size(c.oid) ELSE 0 END)::bigint AS total_bytes,
           sum(CASE WHEN c.relkind IN ('r','m')
                    THEN pg_indexes_size(c.oid) ELSE 0 END)::bigint AS index_bytes
    FROM members m JOIN pg_class c ON c.oid=m.member_oid
    GROUP BY root_oid
)
SELECT root_oid::regclass AS table_family, physical_tables, total_bytes,
       pg_size_pretty(total_bytes) AS total,
       pg_size_pretty(index_bytes) AS indexes
FROM totals ORDER BY total_bytes DESC LIMIT 30;

\echo '== 2. Largest indexes with usage since stats reset'
SELECT s.schemaname || '.' || s.relname AS table, s.indexrelname AS index,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size,
       s.idx_scan, i.indisunique AS uniq, i.indisprimary AS primary_key,
       EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid=s.indexrelid)
           AS constraint_dependency,
       pg_get_indexdef(s.indexrelid) AS def
FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
ORDER BY pg_relation_size(s.indexrelid) DESC LIMIT 60;

\echo '== 3. Non-unique indexes with zero recorded scans > 10 MB (review only)'
SELECT s.schemaname || '.' || s.relname AS table, s.indexrelname AS index,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
  AND pg_relation_size(s.indexrelid) > 10 * 1024 * 1024
ORDER BY pg_relation_size(s.indexrelid) DESC;

\echo '== 3b. Catalog-equivalent nonunique B-tree indexes (candidates only; no DROP)'
-- Match definitions, storage options and attribute options; exclude constraints,
-- replica identity, clustering, comments and dependency-protected indexes.
-- This does not classify a larger covering/prefix index as an exact duplicate.
WITH definitions AS (
    SELECT c.oid, i.indrelid AS table_oid,
           n.nspname AS schema_name, c.relname AS index_name,
           jsonb_build_array(
             c.relam, c.reltablespace, c.reloptions, c.relpersistence, c.relowner,
             i.indnatts, i.indnkeyatts, i.indnullsnotdistinct, i.indimmediate,
             i.indkey::text, i.indcollation::text, i.indclass::text,
             i.indoption::text, i.indexprs::text, i.indpred::text,
             (SELECT jsonb_agg(jsonb_build_array(a.attstattarget,a.attoptions)
                               ORDER BY a.attnum)
              FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0)
           ) AS signature
    FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_index i ON i.indexrelid=c.oid
    JOIN pg_am am ON am.oid=c.relam
    WHERE c.relkind='i' AND am.amname='btree' AND n.nspname !~ '^pg_'
      AND NOT i.indisunique AND NOT i.indisprimary AND NOT i.indisexclusion
      AND i.indisvalid AND i.indisready AND i.indislive AND NOT i.indcheckxmin
      AND NOT i.indisclustered AND NOT i.indisreplident
      AND obj_description(c.oid,'pg_class') IS NULL
      AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid=c.oid)
      AND NOT EXISTS (SELECT 1 FROM pg_depend dep
                      WHERE dep.refclassid='pg_class'::regclass AND dep.refobjid=c.oid)
      AND NOT EXISTS (SELECT 1 FROM pg_depend dep
                      WHERE dep.classid='pg_class'::regclass AND dep.objid=c.oid
                        AND dep.deptype IN ('i','e','x','P','S'))
)
SELECT a.table_oid::regclass AS table_name,
       a.oid::regclass AS first_equivalent_index,
       b.oid::regclass AS second_equivalent_index,
       pg_relation_size(b.oid) AS second_index_bytes,
       pg_size_pretty(pg_relation_size(b.oid)) AS second_index_size,
       pg_get_indexdef(b.oid) AS definition
FROM definitions a JOIN definitions b
  ON a.table_oid=b.table_oid AND a.signature=b.signature AND a.oid<b.oid
ORDER BY pg_relation_size(b.oid) DESC LIMIT 100;

\echo '== 4. Dead tuples / vacuum state (bloat signal)'
SELECT schemaname || '.' || relname AS table, n_live_tup, n_dead_tup,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
       last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
WHERE n_live_tup + n_dead_tup > 100000
ORDER BY n_dead_tup DESC LIMIT 25;

\echo '== 5. Column null fraction / width on the big content tables (pg_stats)'
SELECT schemaname || '.' || tablename AS table, attname, null_frac, avg_width, n_distinct
FROM pg_stats
WHERE tablename IN ('content_media_asso', 'content_mentions', 'bought_content', 'media',
                    'media_urls', 'drm_manifest', 'filepaths', 'x_posts', 'x_messages',
                    'histo_user_infos', 'user_profile_media', 'websocket_messages',
                    'database_write_receipts', 'job_tasks', 'execution_attempts',
                    'execution_work', 'execution_work_payloads',
                    'job_task_identities', 'execution_attempt_identities')
ORDER BY 1, 2;

\echo '== 6. Stats reset time (how much idx_scan history we have)'
SELECT stats_reset FROM pg_stat_database WHERE datname = current_database();
\echo '== 7. Applied alembic revision'
SELECT * FROM alembic_version;

\echo '== 8. WAL policy (configuration values are not actual disk usage)'
SELECT name, setting, unit, pending_restart
FROM pg_settings
WHERE name IN ('max_wal_size','min_wal_size','wal_keep_size',
               'max_slot_wal_keep_size','checkpoint_timeout','wal_compression',
               'archive_mode','fsync','full_page_writes','synchronous_commit')
ORDER BY name;

\echo '== 9. Replication retention and archive failures (not authorization to remove either)'
SELECT slot_name, slot_type, active, wal_status, safe_wal_size,
       CASE WHEN NOT pg_is_in_recovery() AND restart_lsn IS NOT NULL
            THEN pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn)::bigint END
            AS approximate_retained_wal_bytes
FROM pg_replication_slots;
SELECT archived_count, failed_count, last_archived_time, last_failed_time, stats_reset
FROM pg_stat_archiver;
