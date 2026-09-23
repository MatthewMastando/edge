"""Apply supabase/migrations/*.sql in order to a plain Postgres database.

`supabase db reset` / `supabase migration up` are the normal path. This runner exists for CI
(a `postgres` service container) and for machines without Docker. It records applied files in
`public.schema_migrations` so it is safe to re-run.

Usage:
    uv run python scripts/apply_migrations.py [--database-url URL] [--seed]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
SEED_FILE = REPO_ROOT / "supabase" / "seed.sql"

TRACKING_TABLE_SQL = """
create table if not exists public.schema_migrations (
  version text primary key,
  checksum text not null,
  applied_at timestamptz not null default now()
);
"""


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.is_file())


def apply_migrations(database_url: str, *, seed: bool = False, quiet: bool = False) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url) as conn:
        conn.execute(TRACKING_TABLE_SQL)
        conn.commit()
        for path in migration_files():
            version = path.stem
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            row = conn.execute(
                "select checksum from public.schema_migrations where version = %s", (version,)
            ).fetchone()
            if row is not None:
                if row[0] != checksum:
                    msg = f"{path.name} was modified after being applied (checksum mismatch)"
                    raise RuntimeError(msg)
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))  # type: ignore[arg-type]
                conn.execute(
                    "insert into public.schema_migrations (version, checksum) values (%s, %s)",
                    (version, checksum),
                )
            applied.append(path.name)
            if not quiet:
                print(f"applied {path.name}")
        if seed and SEED_FILE.is_file():
            with conn.transaction():
                conn.execute(SEED_FILE.read_text(encoding="utf-8"))  # type: ignore[arg-type]
            if not quiet:
                print(f"applied {SEED_FILE.name}")
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_ADMIN_URL") or os.environ.get("DATABASE_URL"),
        help="Postgres URL (defaults to DATABASE_ADMIN_URL or DATABASE_URL)",
    )
    parser.add_argument("--seed", action="store_true", help="also run supabase/seed.sql")
    args = parser.parse_args(argv)
    if not args.database_url:
        print("error: set DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2
    applied = apply_migrations(args.database_url, seed=args.seed)
    print(f"{len(applied)} migration(s) applied; {len(migration_files())} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
