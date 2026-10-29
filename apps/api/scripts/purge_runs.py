"""Purge every run record so the app starts from a fresh state.

Deletes run rows and everything that hangs off them (steps, evidence, verdicts, DDS documents,
SAP actions). Seed data (suppliers, parcels, seed records, operator settings) and submitted
records are kept. Dry run by default.

Usage (from the repo root, with the API stopped):
    uv run python apps/api/scripts/purge_runs.py            # dry run: prints counts only
    uv run python apps/api/scripts/purge_runs.py --yes      # delete rows, then VACUUM
    uv run python apps/api/scripts/purge_runs.py --yes --files   # also delete trace JSON files

A timestamped copy of the database is written first, unless --no-backup is given.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "sqlite+aiosqlite:///"
# Children first. The foreign keys cascade, but explicit order keeps the counts honest.
TABLES = ["sap_actions", "dds_documents", "verdicts", "evidence", "run_steps", "runs"]
TRACE_DIRS = [ROOT / "data" / "runs" / "agents", ROOT / "data" / "dds"]


def database_path() -> Path:
    env = ROOT / ".env"
    url = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    if not url.startswith(PREFIX):
        sys.exit(f"DATABASE_URL must start with {PREFIX} (found {url or 'nothing'})")
    path = Path(url[len(PREFIX) :])
    return path if path.is_absolute() else ROOT / path


def api_is_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    parser.add_argument(
        "--files", action="store_true", help="also delete trace JSON in data/runs and data/dds"
    )
    parser.add_argument("--no-backup", action="store_true", help="skip the database copy")
    args = parser.parse_args()

    db = database_path()
    if not db.exists():
        sys.exit(f"database not found: {db}")
    if api_is_up():
        sys.exit("the API is running on 127.0.0.1:8000; stop it first (it caches run state in memory)")

    with sqlite3.connect(db) as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    files = [p for d in TRACE_DIRS if d.exists() for p in d.glob("*.json")]

    print(f"database: {db}")
    for table in TABLES:
        print(f"  {table:<14} {counts[table]:>6} rows")
    print(f"  trace files   {len(files):>6} ({', '.join(str(d.relative_to(ROOT)) for d in TRACE_DIRS)})")
    if not args.yes:
        print("dry run: nothing deleted. Re-run with --yes to purge.")
        return 0

    if not args.no_backup:
        backup = db.with_name(f"{db.stem}.before-purge-{datetime.now(UTC):%Y%m%dT%H%M%S}{db.suffix}")
        shutil.copy2(db, backup)
        print(f"backup: {backup}")

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        leftover = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        conn.execute("VACUUM")
    if any(leftover.values()):
        sys.exit(f"rows left after purge: {leftover}")
    print("deleted run rows; VACUUM done")

    if args.files:
        for path in files:
            path.unlink()
        print(f"deleted {len(files)} trace files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
