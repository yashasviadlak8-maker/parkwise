"""Shared CockroachDB adapter for Package B and Package C."""
import os
import re
import time

import psycopg
from psycopg import errors
from psycopg.rows import dict_row


def _connect():
    dsn = os.getenv(
        "CRDB_URL",
        "postgresql://root@localhost:26257/parkwise?sslmode=disable",
    )
    return psycopg.connect(dsn, row_factory=dict_row)


def _sql(sql):
    """Translate Oracle/SQLite-style :named placeholders to psycopg placeholders."""
    return re.sub(r"(?<![:\w]):(\w+)", r"%(\1)s", sql)


def run(sql, params=None, tries=5):
    """Execute SQL with retries for CockroachDB serialization failures."""
    for attempt in range(tries):
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_sql(sql), params or {})
                    if cur.description is None:
                        return []
                    return [
                        {key.lower(): value for key, value in row.items()}
                        for row in cur.fetchall()
                    ]
        except (errors.SerializationFailure, errors.DeadlockDetected):
            if attempt == tries - 1:
                raise
            time.sleep(0.05 * (2 ** attempt))


def query(sql, p=None):
    return run(sql, p)


def execute(sql, p=None):
    run(sql, p)


def next_id(table, pk):
    """Compatibility ID helper for legacy tables without generated IDs."""
    if not table.replace("_", "").isalnum() or not pk.replace("_", "").isalnum():
        raise ValueError("Invalid table or column name")
    rows = query(f'SELECT COALESCE(MAX("{pk}"), 0) + 1 AS n FROM "{table}"')
    return rows[0]["n"]
