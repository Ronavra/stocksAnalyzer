# Local history with a smaller Supabase database

The full price and feature history is kept in a SQLite file on the API computer. Supabase retains 400 calendar days of prices and 1,100 days of features (enough for the existing 750-session setup window). Recommendations, outcomes, membership intervals, observations, financials, earnings, disclosures and current dashboards stay in Supabase. Neither recommendation weights nor model promotion thresholds change.

Retention is inactive until a full export and a separate backup are verified. The migration locks both market tables, checks every expired source row against both copies, then enables the policy and deletes exactly those verified rows in one transaction. A missing copy, changed source row, dependency or count mismatch aborts deletion. `VACUUM FULL` is a separate compaction step which briefly locks tables; pause running ingestion/repair jobs and the API before the initial migration. Keep both archive files, preferably putting the backup on another disk. The first export itself incurs additional egress; it does not refund existing usage or promise immediate removal of a Fair Use restriction.

## Windows setup

Run in the existing repository after `git pull`, from `services\api`:

1. In Supabase Dashboard, open **Connect → Session pooler** and copy the PostgreSQL URI on port **5432**. Replace the password placeholder **locally**, URL-encoding special characters. Add it to `services/api/.env` as `SUPABASE_DB_URL=...`. Keep the existing `SUPABASE_URL` and service-role key. Do not put this connection string in GitHub or chat. A direct Postgres URI is also supported where IPv6 is available; transaction pooling on port 6543 is unsuitable for this migration's cursors.
2. Stop the API and any active ingestion/repair job. Make sure there is space for two full archive copies and temporary compaction space in Postgres.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate_local_history.ps1
```

To keep the backup on another disk:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate_local_history.ps1 -BackupPath "D:\stocksAnalyzer-backups\market-history.sqlite3"
```

The script installs pinned archive dependencies, exports/verifies both copies, prunes, compacts, checks the real remaining database size, writes `LOCAL_MARKET_ARCHIVE` and `LOCAL_MARKET_ARCHIVE_BACKUP` to this computer's `.env`, and installs daily 08:00 and Friday 18:00 Israel-time tasks. A result above 500 MB is reported as unfinished, rather than assuming this retention policy will always fit. Re-run the API normally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The computer must be on and the account signed in for these tasks. Supabase Data API access must also be restored for daily research/publication; the Postgres migration may remain blocked by database/network/account restrictions. Billing-period usage averages can keep a size restriction active even after the physical database has shrunk.

## Export only / ongoing maintenance

To inspect a migration without deleting cloud rows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-archive.txt
.\.venv\Scripts\python.exe scripts\archive_market_history.py --backup "D:\stocksAnalyzer-backups\market-history.sqlite3"
```

`--prune` is explicit. `--maintain` requires an existing verified full export and fetches only newly expiring rows, not the full multi-year cloud dataset. The independent daily scheduler runs verified maintenance before its refresh if both archive paths are configured, including when GitHub refreshed first. Cleanup uses the documented session-only write override for oversized Free Plan databases; it does not change the global read-only setting or billing restriction. If compaction did not complete, pause jobs and run:

```powershell
.\.venv\Scripts\python.exe scripts\archive_market_history.py --maintain --prune --compact
```

## Reading and writing after migration

The archive-aware client supports existing price/feature queries, pagination and provider preference. Per company/process it refreshes the recent 90-day window (or any missed period) from Supabase, merging current rows into the archive before answering a query. Older rows are read locally. New full-history writes are saved locally; only rows within retention are sent to Supabase. Missing/invalid archives fail explicitly. Retained server rows use their full payload so partial API writes do not erase archived metadata.

Daily hosted refreshes can continue against the bounded cloud history. New constituents bootstrap bounded history there; run ingestion on the archive computer to collect their full history. Unbounded historical reads and writes of old rows without a local archive fail explicitly. Hosted full-history model validation/backtests defer to the archive computer after retention activates; they cannot promote a model from an accidentally shortened training dataset. The Friday local task runs the same validation scripts and gates. Frozen published cohorts remain unchanged.

SQL label-repair RPCs operate on cloud rows. Repairs of archived prices/features must run on the archive computer using the Python historical rebuild (`build_daily_price_features.py --full`) so both local data and retained cloud rows are updated. Do not interpret a cloud-only repair as verification of the archived years.

Archive files contain the full original JSON records, including IDs and source timestamps, plus row checksums. They are excluded from git and are never uploaded as CI artifacts. Back up the primary file regularly; the migration's separate verified copy contains the exported data even if pruning or compaction is interrupted. Re-enabling unbounded cloud history requires disabling the policy and restoring data from this archive with sufficient database capacity; do not delete the archive when the cloud starts working.
