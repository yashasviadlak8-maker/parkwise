#!/usr/bin/env python3
"""ParkWise DA3: Work Package C — CockroachDB Business Logic

Implements the three required Person C business logic functions:
  1. register_vehicle(user_id, plate, type, attr1, attr2, attr3)
     - Validates user existence and REGISTERED customer status.
     - Normalizes plate to uppercase and validates against ^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$.
     - Validates vehicle type ('CAR', 'BIKE', 'TRUCK', 'EV') and subtype attributes against schema.
     - Atomically inserts supertype (vehicle) and exactly one matching subtype in one transaction.
     - Handles CockroachDB serialization failures (SQLSTATE 40001) with exponential backoff.
     - Returns created vehicle_id.

  2. topup_wallet(user_id, amount)
     - Validates positive amount <= 10,000.
     - Verifies user exists, is REGISTERED, and has KYC status 'VERIFIED'.
     - Atomically increments wallet_balance and returns updated balance.
     - Retries serialization failures safely.

  3. zone_monthly_revenue(zone, month, year)
     - Joins payment -> booking -> parking_slot -> parking_lot -> zone_config.
     - Sums SUCCESS payment amounts minus REFUNDED payment amounts in the requested month/year.
     - Returns 0.0 (not NULL) when no qualifying payments exist.
     - Supports both numeric zone_id (e.g. 1) and zone_name (e.g. 'NORTH').

Contract Compliance:
  - Uses psycopg v3 and the CRDB_URL environment variable.
  - Parameterized queries with %s markers; zero literal percent signs inside SQL text.
  - Multi-statement operations execute within a single atomic transaction.
"""

from __future__ import annotations
from decimal import Decimal
import os
import re
import time
from typing import Any

# License plate pattern: e.g. "TN 22 AB 1234", "KA 01 E 5678", "DL 04 CCC 9999"
PLATE_REGEX = re.compile(r"^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$")
VALID_VEHICLE_TYPES = ("CAR", "BIKE", "TRUCK", "EV")
MAX_RETRIES = 5

try:
    import psycopg
except ImportError:
    psycopg = None  # Handled with actionable error if invoked without driver


def get_crdb_url() -> str:
    """Return CockroachDB connection URL from environment or local default."""
    return os.environ.get("CRDB_URL", "postgresql://root@localhost:26257/parkwise?sslmode=disable")


def _get_connection():
    """Create a psycopg v3 connection using get_crdb_url()."""
    if psycopg is None:
        raise RuntimeError("psycopg v3 is not installed. Install via: pip install 'psycopg[binary]'")
    return psycopg.connect(get_crdb_url())


def _run_with_retry(func, conn=None, max_retries: int = MAX_RETRIES):
    """Execute a callable inside a transaction with exponential backoff on SQLSTATE 40001."""
    if conn is not None:
        for attempt in range(max_retries):
            try:
                with conn.transaction():
                    return func(conn)
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None)
                if sqlstate in ("40001", "40P01"):
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(0.05 * (2 ** attempt))
                    continue
                raise

    # Manage connection lifecycle if not provided by caller
    if psycopg is None:
        raise RuntimeError("psycopg v3 is not installed. Install via: pip install 'psycopg[binary]'")

    db_url = get_crdb_url()
    for attempt in range(max_retries):
        try:
            with psycopg.connect(db_url) as managed_conn:
                with managed_conn.transaction():
                    return func(managed_conn)
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate in ("40001", "40P01"):
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.05 * (2 ** attempt))
                continue
            raise


# ============================================================================
# 1. Register Vehicle
# ============================================================================

def register_vehicle(
    user_id: int,
    plate: str,
    type: str,
    attr1: Any = None,
    attr2: Any = None,
    attr3: Any = None,
    conn=None,
) -> int:
    """Register a new vehicle and its subtype row in one atomic transaction.

    Args:
        user_id: ID of the registered user owning the vehicle.
        plate: License plate string (will be normalized to uppercase).
        type: Vehicle type discriminator ('CAR', 'BIKE', 'TRUCK', 'EV').
        attr1: Subtype attribute 1 (CAR: length_m, BIKE: engine_cc, TRUCK: max_weight_tons, EV: battery_capacity_kwh).
        attr2: Subtype attribute 2 (CAR: width_m, BIKE: is_electric, TRUCK: height_m, EV: connector_type).
        attr3: Subtype attribute 3 (CAR: needs_ev_charging, BIKE: unused, TRUCK: axle_count, EV: charging_speed_kw).
        conn: Optional existing psycopg connection.

    Returns:
        int: Created vehicle_id.
    """
    # 1. Validate Plate Format
    if not plate or not isinstance(plate, str):
        raise ValueError("License plate must be a non-empty string.")
    norm_plate = plate.strip().upper()
    if not PLATE_REGEX.match(norm_plate):
        raise ValueError(
            f"Invalid license plate format '{plate}'. Must match standard pattern 'TN 22 AB 1234'."
        )

    # 2. Validate Vehicle Type
    if not type or not isinstance(type, str):
        raise ValueError("Vehicle type must be a non-empty string.")
    norm_type = type.strip().upper()
    if norm_type not in VALID_VEHICLE_TYPES:
        raise ValueError(
            f"Invalid vehicle type '{type}'. Must be one of {VALID_VEHICLE_TYPES}."
        )

    # 3. Validate and Parse Subtype Attributes
    parsed_attrs = _parse_subtype_attrs(norm_type, attr1, attr2, attr3)

    def _txn_work(tx_conn):
        with tx_conn.cursor() as cur:
            # Verify user exists and is a REGISTERED customer
            cur.execute(
                """
                SELECT u.user_id, u.user_type, r.user_id
                FROM user_master u
                LEFT JOIN registered_user r ON u.user_id = r.user_id
                WHERE u.user_id = %s;
                """,
                (user_id,),
            )
            user_row = cur.fetchone()
            if not user_row:
                raise ValueError(f"User with user_id={user_id} does not exist.")

            _, user_type, reg_uid = user_row
            if user_type != "REGISTERED" or reg_uid is None:
                raise ValueError(
                    f"User {user_id} is not a REGISTERED customer (user_type='{user_type}'). "
                    f"Only registered customers can own vehicles."
                )

            # Insert supertype vehicle record
            try:
                cur.execute(
                    """
                    INSERT INTO vehicle (user_id, license_plate, vehicle_type)
                    VALUES (%s, %s, %s)
                    RETURNING vehicle_id;
                    """,
                    (user_id, norm_plate, norm_type),
                )
                vid = cur.fetchone()[0]
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None)
                if sqlstate == "23505":  # unique_violation
                    raise ValueError(f"Vehicle with license plate '{norm_plate}' is already registered.") from exc
                raise

            # Insert corresponding subtype record
            _insert_subtype(cur, vid, norm_type, parsed_attrs)
            return int(vid)

    return _run_with_retry(_txn_work, conn=conn)


def _parse_subtype_attrs(vtype: str, a1: Any, a2: Any, a3: Any) -> dict[str, Any]:
    """Validate and convert subtype attributes against schema column types."""
    if vtype == "CAR":
        length_m = float(a1) if a1 is not None and a1 != "" else None
        width_m = float(a2) if a2 is not None and a2 != "" else None
        needs_charging = int(a3) if a3 is not None and a3 != "" else 0
        if needs_charging not in (0, 1):
            raise ValueError(f"needs_ev_charging must be 0 or 1 (got {a3}).")
        return {"length_m": length_m, "width_m": width_m, "needs_ev_charging": needs_charging}

    elif vtype == "BIKE":
        engine_cc = int(a1) if a1 is not None and a1 != "" else None
        is_electric = int(a2) if a2 is not None and a2 != "" else 0
        if is_electric not in (0, 1):
            raise ValueError(f"is_electric must be 0 or 1 (got {a2}).")
        return {"engine_cc": engine_cc, "is_electric": is_electric}

    elif vtype == "TRUCK":
        max_weight = float(a1) if a1 is not None and a1 != "" else None
        height_m = float(a2) if a2 is not None and a2 != "" else None
        axle_count = int(a3) if a3 is not None and a3 != "" else None
        return {"max_weight_tons": max_weight, "height_m": height_m, "axle_count": axle_count}

    elif vtype == "EV":
        battery_kwh = float(a1) if a1 is not None and a1 != "" else None
        connector = str(a2).strip() if a2 is not None and str(a2).strip() != "" else None
        charging_speed = float(a3) if a3 is not None and a3 != "" else None
        return {
            "battery_capacity_kwh": battery_kwh,
            "connector_type": connector,
            "charging_speed_kw": charging_speed,
        }

    raise ValueError(f"Unsupported vehicle type: {vtype}")


def _insert_subtype(cur, vehicle_id: int, vtype: str, attrs: dict[str, Any]) -> None:
    """Insert into the appropriate vehicle subtype table."""
    if vtype == "CAR":
        cur.execute(
            """
            INSERT INTO vehicle_car (vehicle_id, length_m, width_m, needs_ev_charging)
            VALUES (%s, %s, %s, %s);
            """,
            (vehicle_id, attrs["length_m"], attrs["width_m"], attrs["needs_ev_charging"]),
        )
    elif vtype == "BIKE":
        cur.execute(
            """
            INSERT INTO vehicle_bike (vehicle_id, engine_cc, is_electric)
            VALUES (%s, %s, %s);
            """,
            (vehicle_id, attrs["engine_cc"], attrs["is_electric"]),
        )
    elif vtype == "TRUCK":
        cur.execute(
            """
            INSERT INTO vehicle_truck (vehicle_id, max_weight_tons, height_m, axle_count)
            VALUES (%s, %s, %s, %s);
            """,
            (vehicle_id, attrs["max_weight_tons"], attrs["height_m"], attrs["axle_count"]),
        )
    elif vtype == "EV":
        cur.execute(
            """
            INSERT INTO vehicle_ev (vehicle_id, battery_capacity_kwh, connector_type, charging_speed_kw)
            VALUES (%s, %s, %s, %s);
            """,
            (vehicle_id, attrs["battery_capacity_kwh"], attrs["connector_type"], attrs["charging_speed_kw"]),
        )


# ============================================================================
# 2. Top-up Wallet
# ============================================================================

def topup_wallet(user_id: int, amount: float | int, conn=None) -> float:
    """Add funds to a registered user's wallet with verification and atomicity.

    Args:
        user_id: ID of the registered user.
        amount: Top-up amount (must be positive and <= 10,000).
        conn: Optional existing psycopg connection    Returns:
        float: Updated wallet balance.
    """

    from decimal import Decimal, InvalidOperation

    try:
        amt = Decimal(str(amount))
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError(f"Top-up amount must be a valid number (got {amount}).")

    if not amt.is_finite():
        raise ValueError("Top-up amount must be a finite number.")

    if amt <= 0:
        raise ValueError(f"Top-up amount must be strictly positive (got {amt}).")

    if amt > Decimal("10000"):
        raise ValueError(f"Top-up amount cannot exceed 10,000 (got {amt}).")

    def _txn_work(tx_conn):
        with tx_conn.cursor() as cur:
            # Query user and KYC status
            cur.execute(
                """
                SELECT u.user_id, u.user_type, r.kyc_status, r.wallet_balance
                FROM user_master u
                JOIN registered_user r ON u.user_id = r.user_id
                WHERE u.user_id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Registered user with user_id={user_id} does not exist.")

            _, user_type, kyc_status, _ = row
            if user_type != "REGISTERED":
                raise ValueError(f"User {user_id} is not a registered customer (user_type='{user_type}').")

            if kyc_status != "VERIFIED":
                raise ValueError(
                    f"User {user_id} KYC status is '{kyc_status}'. "
                    f"Wallet top-up requires 'VERIFIED' status."
                )

            # Atomically update balance and return new total
            cur.execute(
                """
                UPDATE registered_user
                SET wallet_balance = wallet_balance + %s::DECIMAL
                WHERE user_id = %s
                RETURNING wallet_balance;
                """,
                (amt, user_id),
            )
            new_balance = cur.fetchone()[0]
            return float(new_balance)

    return _run_with_retry(_txn_work, conn=conn)


# ============================================================================
# 3. Zone Monthly Revenue
# ============================================================================

def zone_monthly_revenue(zone: int | str, month: int, year: int, conn=None) -> float:
    """Calculate net revenue for a zone in a given month and year.

    Calculates:
      Net Revenue = SUM(SUCCESS payments) - SUM(REFUNDED payments)
      Returns 0.0 (not NULL) when no qualifying payments exist.

    Joins:
      payment -> booking -> parking_slot -> parking_lot -> zone_config

    Args:
        zone: Zone identifier (zone_id integer or zone_name string e.g. 'NORTH').
        month: Calendar month (1 to 12).
        year: Calendar year (e.g. 2026).
        conn: Optional existing psycopg connection.

    Returns:
        float: Net monthly revenue for the zone.
    """
    try:
        m = int(month)
        y = int(year)
    except (ValueError, TypeError):
        raise ValueError(f"Month and year must be integers (got month={month}, year={year}).")

    if not (1 <= m <= 12):
        raise ValueError(f"Month must be between 1 and 12 (got {m}).")
    if y < 2000 or y > 2100:
        raise ValueError(f"Year out of plausible range: {y}.")

    zone_str = str(zone).strip()
    zone_id = None
    try:
        zone_id = int(zone_str)
    except ValueError:
        zone_id = None

    if zone_id is not None:
        zone_clause = "(z.zone_id = %s OR UPPER(z.zone_name) = UPPER(%s))"
        params = (zone_id, zone_str, m, y)
    else:
        zone_clause = "UPPER(z.zone_name) = UPPER(%s)"
        params = (zone_str, m, y)

    sql = f"""
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN p.status = 'SUCCESS' THEN p.amount
                    WHEN p.status = 'REFUNDED' THEN -p.amount
                    ELSE 0.00
                END
            ),
            0.00
        ) AS net_revenue
        FROM payment p
        JOIN booking b ON p.booking_id = b.booking_id
        JOIN parking_slot s ON b.zone_id = s.zone_id AND b.slot_id = s.slot_id
        JOIN parking_lot l ON s.zone_id = l.zone_id AND s.lot_id = l.lot_id
        JOIN zone_config z ON l.zone_id = z.zone_id
        WHERE {zone_clause}
          AND EXTRACT(MONTH FROM p.payment_timestamp) = %s
          AND EXTRACT(YEAR FROM p.payment_timestamp) = %s;
    """

    def _query_work(tx_conn):
        with tx_conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row or row[0] is None:
                return 0.0
            return float(row[0])

    return _run_with_retry(_query_work, conn=conn)


__all__ = [
    "register_vehicle",
    "topup_wallet",
    "zone_monthly_revenue",
    "get_crdb_url",
]
