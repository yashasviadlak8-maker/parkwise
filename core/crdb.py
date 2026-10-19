"""CockroachDB backend adapter for the shared ParkWise data-access layer."""
import os
import psycopg
from psycopg.rows import dict_row


def _connect():
    dsn = os.getenv(
        "CRDB_URL",
        "postgresql://root@localhost:26257/parkwise?sslmode=disable",
    )
    return psycopg.connect(dsn, row_factory=dict_row)


def query(sql, p=None):
    """Execute a read query and return rows as lowercase-key dictionaries."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, p or {})
            if cur.description is None:
                return []
            return [
                {key.lower(): value for key, value in row.items()}
                for row in cur.fetchall()
            ]


def execute(sql, p=None):
    """Execute a write query and commit it."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, p or {})


def next_id(table, pk):
    """Compatibility helper; CockroachDB tables should preferably use generated IDs."""
    if not table.replace("_", "").isalnum() or not pk.replace("_", "").isalnum():
        raise ValueError("Invalid table or column name")
    rows = query(f'SELECT COALESCE(MAX("{pk}"), 0) + 1 AS n FROM "{table}"')
    return rows[0]["n"]
