# Pattern Finder Local Runtime, SQLite, and Dashboard Design

## Scope

This design implements M3C-B, M3C-C, and M3C-D only. It preserves the M3C-A Task 12 Snapshot read model and does not add Pattern types, trading, cloud services, Docker, PostgreSQL, or multi-user behavior.

## Baseline

- Base dependency: PR #26 head `0e80e2cba5acf2fd8da547811599103536b0f627` because Task 12 is still a Draft PR and is not present on the M3C-A base branch.
- Existing Profile and Universe Snapshot files remain authoritative and are never deleted by this work.
- Snapshot determinism, immutable Profile versions, S0-S10 semantics, provenance, and hashes remain unchanged.

## Architecture

The UI calls a read-only application service. The application service calls Repository interfaces backed by SQLite. SQLite connections and migrations are owned by the persistence package; UI files never import `sqlite3`.

The database stores the exact canonical Snapshot JSON plus relational projections for discovery and diagnostics. Loading a Snapshot decodes the exact JSON through the existing Snapshot codec, which revalidates all Profile bindings, row order, provenance, Funnel, members hash, content hash, and record hash. Relational S0 and S10 rows are explicit projections around the unchanged persisted S1-S9 decisions; they never feed Snapshot construction.

## Runtime

Runtime configuration resolves the repository root from the module location and supports environment overrides for database, logs, host, and port. A PID record binds PID, repository root, app path, host, and port. Health is true only when the PID record belongs to this repository, the PID is alive, the configured port accepts connections, Streamlit's health endpoint responds, and SQLite is connected at the expected schema version.

The Windows launcher invokes the Python runtime CLI. Startup applies migrations before spawning Streamlit, rejects an unrelated port owner, avoids duplicate instances, records logs, and opens the browser. Stop verifies ownership before terminating the recorded process.

## Database

Schema v1 contains `schema_migrations`, `app_runs`, `audit_events`, `system_settings`, `profiles`, `profile_versions`, `profile_rules`, `universe_snapshots`, `snapshot_securities`, `snapshot_security_decisions`, `scan_batches`, `pattern_candidates`, `manual_reviews`, `backtest_runs`, and `backtest_horizons`. Foreign keys are enabled on every connection. Migrations run in one explicit transaction, have checksums, and roll back on failure. Triggers reject update/delete of published Profile versions and immutable Snapshot records.

Legacy import is read-validate-write-verify. It supports dry-run, reports imported/skipped/conflict/error counts, compares row count and all Snapshot hashes, and never deletes source files.

## Dashboard

The default home page is the system dashboard. It reports live system, database, schema, Futu, active Profile, latest Snapshot counts, latest Scan, candidate and pending review counts, latest Backtest, and data freshness. Project Progress is loaded from `config/project_progress.yaml`; percentages are computed from completed task entries. Diagnostics reports non-secret runtime paths, versions, PID, port, uptime, latest migration/error, Futu reachability, and latest Snapshot integrity.

## Verification

Each phase receives focused tests. Final verification runs Pattern Finder regression, full repository tests, compileall, launcher contract checks, migration rollback/foreign-key checks, legacy Snapshot round-trip/hash checks, Streamlit page tests, and `git diff --check`.
