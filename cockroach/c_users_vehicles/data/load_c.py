#!/usr/bin/env python3
"""ParkWise DA3: Work Package C — CockroachDB Data Loader

Loads deterministic seed data into CockroachDB for all 9 Package C tables:
  1. user_master
  2. registered_user
  3. admin_user
  4. parking_attendant
  5. vehicle
  6. vehicle_car
  7. vehicle_bike
  8. vehicle_truck
  9. vehicle_ev

Safety & Contract Enforcement:
  - Connects via CRDB_URL environment variable (psycopg v3).
  - Strict foreign-key dependency ordering: supertypes first, followed by subtypes.
  - Single atomic transaction: all 9 tables are loaded and verified in one transaction.
    Any failure rolls back all tables cleanly, leaving zero partial datasets.
  - Conflict safety: verifies that any pre-existing rows in the seed ID range match
    the expected generated records exactly. Aborts on mismatched or conflicting data.
  - Safe parameterization: batch inserts via psycopg executemany (%s).
  - Safe reruns: ON CONFLICT (pk) DO NOTHING safely populates missing rows while
    preserving verified existing data.
  - Leaves parent-table stubs completely untouched.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent

# Loading order strictly respecting foreign keys
TABLE_ORDER = [
    ("user_master", "user_id"),
    ("registered_user", "user_id"),
    ("admin_user", "user_id"),
    ("parking_attendant", "user_id"),
    ("vehicle", "vehicle_id"),
    ("vehicle_car", "vehicle_id"),
    ("vehicle_bike", "vehicle_id"),
    ("vehicle_truck", "vehicle_id"),
    ("vehicle_ev", "vehicle_id"),
]

EXPECTED_COUNTS = {
    "user_master": 1500,
    "registered_user": 1400,
    "admin_user": 40,
    "parking_attendant": 60,
    "vehicle": 2000,
    "vehicle_car": 1000,
    "vehicle_bike": 500,
    "vehicle_truck": 200,
    "vehicle_ev": 300,
}


def get_crdb_url(cli_url: str | None = None) -> str:
    url = cli_url or os.environ.get("CRDB_URL")
    if not url:
        url = "postgresql://root@localhost:26257/parkwise?sslmode=disable"
    return url


def load_csv(table_name: str) -> list[dict[str, str]]:
    csv_file = DATA_DIR / f"{table_name}.csv"
    if not csv_file.is_file():
        print(f"CSV {csv_file.name} not found. Invoking generator...")
        try:
            from generate_c import write_csvs
            write_csvs(DATA_DIR)
        except Exception as exc:
            raise RuntimeError(f"Failed to auto-generate CSVs: {exc}") from exc

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _values_match(actual_val: any, expected_val: str, col_name: str) -> bool:
    """Compare database column value with CSV string value with type tolerance."""
    if actual_val is None:
        return expected_val is None or expected_val == ""

    act_str = str(actual_val).strip()
    exp_str = str(expected_val).strip()

    if act_str == exp_str:
        return True

    # Floating point / Decimal comparison
    try:
        if abs(float(act_str) - float(exp_str)) < 1e-4:
            return True
    except (ValueError, TypeError):
        pass

    # Date / Timestamp tolerance (e.g. '2026-08-02' vs '2026-08-02 00:00:00')
    if "created_at" in col_name or "last_login" in col_name or "registration_date" in col_name:
        if act_str.split(" ")[0] == exp_str.split(" ")[0]:
            return True

    return False


def load_table(cur, table_name: str, pk_col: str, batch_size: int = 500) -> tuple[int, int, int]:
    """Load a single table within an ongoing transaction.

    Verifies existing rows match seed data, inserts missing rows, and validates exact IDs and values.
    Returns: (inserted_count, total_count_in_db, matched_existing_count).
    """
    rows = load_csv(table_name)
    if not rows:
        return 0, 0, 0

    cols = list(rows[0].keys())
    col_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders}) ON CONFLICT ({pk_col}) DO NOTHING;"

    expected_lookup = {str(r[pk_col]): r for r in rows}
    expected_ids = set(expected_lookup.keys())
    target_ids = [int(r[pk_col]) for r in rows]
    min_id, max_id = min(target_ids), max(target_ids)

    # 1. Check pre-existing rows in database for target ID range
    cur.execute(f"SELECT count(*) FROM {table_name};")
    pre_total = cur.fetchone()[0]

    matched_existing = 0
    if pre_total > 0:
        cur.execute(
            f"SELECT {col_str} FROM {table_name} WHERE {pk_col} >= %s AND {pk_col} <= %s ORDER BY {pk_col};",
            (min_id, max_id),
        )
        existing_rows = cur.fetchall()

        for ex_row in existing_rows:
            ex_dict = dict(zip(cols, ex_row))
            pk_val = str(ex_dict[pk_col])
            if pk_val not in expected_lookup:
                raise ValueError(
                    f"Unexpected pre-existing row in table '{table_name}' with {pk_col}={pk_val} "
                    f"in target range [{min_id}, {max_id}]. Aborting load to protect existing data."
                )

            exp_dict = expected_lookup[pk_val]
            for col in cols:
                if not _values_match(ex_dict[col], exp_dict[col], col):
                    raise ValueError(
                        f"Conflicting pre-existing row in table '{table_name}' for {pk_col}={pk_val}. "
                        f"Column '{col}' has value '{ex_dict[col]}', expected seed value '{exp_dict[col]}'. "
                        f"Aborting load to protect existing data."
                    )
            matched_existing += 1

    # 2. Batch insert missing rows
    tuples = [[r[c] for c in cols] for r in rows]
    for i in range(0, len(tuples), batch_size):
        batch = tuples[i : i + batch_size]
        cur.executemany(sql, batch)

    # 3. Verify exact set of actual target-range IDs and row values (do not rely on counts alone)
    cur.execute(
        f"SELECT {col_str} FROM {table_name} WHERE {pk_col} >= %s AND {pk_col} <= %s ORDER BY {pk_col};",
        (min_id, max_id),
    )
    post_target_rows = cur.fetchall()
    actual_lookup = {}
    for r in post_target_rows:
        row_dict = dict(zip(cols, r))
        actual_lookup[str(row_dict[pk_col])] = row_dict

    actual_ids = set(actual_lookup.keys())

    missing_ids = expected_ids - actual_ids
    if missing_ids:
        raise RuntimeError(
            f"Table '{table_name}' load verification failed: missing {len(missing_ids)} expected seed IDs "
            f"in range [{min_id}, {max_id}] (sample missing: {sorted(missing_ids)[:5]})."
        )

    unexpected_ids = actual_ids - expected_ids
    if unexpected_ids:
        raise RuntimeError(
            f"Table '{table_name}' load verification failed: {len(unexpected_ids)} unexpected IDs found "
            f"in range [{min_id}, {max_id}] (sample unexpected: {sorted(unexpected_ids)[:5]})."
        )

    # Verify every target-range row matches expected generated values
    for pk_val, act_dict in actual_lookup.items():
        exp_dict = expected_lookup[pk_val]
        for col in cols:
            if not _values_match(act_dict[col], exp_dict[col], col):
                raise RuntimeError(
                    f"Table '{table_name}' post-load value verification failed for {pk_col}={pk_val}: "
                    f"column '{col}' has value '{act_dict[col]}', expected seed value '{exp_dict[col]}'."
                )

    cur.execute(f"SELECT count(*) FROM {table_name};")
    post_total = cur.fetchone()[0]
    unrelated_count = post_total - len(actual_ids)
    if unrelated_count > 0:
        print(f"    Notice: {unrelated_count} unrelated row(s) exist outside seed range [{min_id}, {max_id}] and were left untouched.")

    inserted = post_total - pre_total
    return inserted, post_total, matched_existing


def run_load(db_url: str) -> bool:
    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg v3 is not installed. Run: pip install 'psycopg[binary]'", file=sys.stderr)
        return False

    print(f"Connecting to CockroachDB at {db_url}...")
    try:
        with psycopg.connect(db_url) as conn:
            print("Connected successfully. Starting atomic data load in dependency order...\n")

            # All 9 tables loaded within a single atomic transaction
            with conn.transaction():
                with conn.cursor() as cur:
                    for table_name, pk_col in TABLE_ORDER:
                        inserted, total, existing_matched = load_table(cur, table_name, pk_col)
                        expected = EXPECTED_COUNTS[table_name]
                        print(
                            f"  [{table_name:18s}] Inserted: {inserted:4d} | "
                            f"Verified Existing: {existing_matched:4d} | "
                            f"Total in DB: {total:4d} (Seed Target: {expected})"
                        )

            print("\n=== Data Load Summary ===")
            print("SUCCESS: All 9 Package C tables loaded, verified, and committed atomically.")
            return True

    except Exception as exc:
        print(f"\nERROR: Data loading failed and entire transaction was rolled back:\n  {exc}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="ParkWise DA3 Package C Data Loader")
    parser.add_argument("--url", help="CockroachDB connection URL (defaults to CRDB_URL or localhost:26257)")
    parser.add_argument("--generate", action="store_true", help="Force regenerate CSV files before loading")
    args = parser.parse_args()

    if args.generate:
        from generate_c import write_csvs
        write_csvs(DATA_DIR)

    db_url = get_crdb_url(args.url)
    success = run_load(db_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
