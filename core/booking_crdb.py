"""Work Package B — CockroachDB transactional booking, exit, penalty, occupancy sync, and refund logic.

All multi-statement transactions use `with conn.transaction():` inside a retry loop
on `psycopg.errors.SerializationFailure` (SQLSTATE 40001) with exponential backoff.
"""
import math
import os
import time
import uuid
from datetime import datetime, timezone
import psycopg
from psycopg.rows import dict_row
from psycopg import errors


def _norm_ts(dt):
    """Ensure datetime has timezone info (UTC default if naive) for TIMESTAMPTZ comparison."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _crdb_url() -> str:
    url = os.environ.get(
        "CRDB_URL", "postgresql://root@127.0.0.1:26257/parkwise?sslmode=disable"
    )
    return url.replace("@localhost:", "@127.0.0.1:")


def _run_txn(fn, tries=25):
    """Execute a callable `fn(conn)` inside a serializable transaction with 40001 retry loop."""
    import random
    last_err = None
    url = _crdb_url()
    for i in range(tries):
        try:
            with psycopg.connect(url, row_factory=dict_row) as conn:
                with conn.transaction():
                    return fn(conn)
        except errors.SerializationFailure as e:
            last_err = e
            time.sleep(0.015 * (1.35 ** min(i, 8)) + random.uniform(0.005, 0.025))
    raise RuntimeError(f"ERR_SERIALIZATION_RETRY_EXHAUSTED: still failing after {tries} retries (SQLSTATE 40001): {last_err}")


def fn_penalty(overstay_min: int) -> float:
    """Call CockroachDB SQL function fn_penalty(p_overstay_min INT8) RETURNS DECIMAL."""
    overstay_min = max(0, int(overstay_min))
    def _op(conn):
        row = conn.execute("SELECT fn_penalty(%(m)s::INT8) AS p", {"m": overstay_min}).fetchone()
        return float(row["p"]) if row and row["p"] is not None else 0.0
    return _run_txn(_op)


def book_slot(user_id: int, vehicle_id: int, slot_id: int, start, end, method: str = "UPI", simulate_error: bool = False):
    """Atomically book a parking slot and record initial payment under Serializable isolation.

    Enforces all business & domain rules with named errors:
      - ERR_INVALID_TIME_WINDOW: end_time must be strictly after start_time
      - ERR_VEHICLE_NOT_FOUND: vehicle_id does not exist
      - ERR_VEHICLE_OWNER_MISMATCH: vehicle does not belong to user_id
      - ERR_VEHICLE_UNVERIFIED: vehicle is_verified != 1
      - ERR_SLOT_NOT_FOUND: slot_id does not exist
      - ERR_LOT_INACTIVE: parking_lot is_active != 1
      - ERR_INCOMPATIBLE_SLOT: TRUCK requires LARGE slot; non-EV cannot book EV slot
      - ERR_SLOT_OVERLAP: overlapping active/confirmed/pending booking on the same slot
    """
    start_dt = _norm_ts(start)
    end_dt = _norm_ts(end)
    if end_dt <= start_dt:
        raise ValueError("ERR_INVALID_TIME_WINDOW: end_time must be after start_time")

    def _txn(conn):
        # 1. Verify vehicle exists, belongs to user_id, and is verified
        veh = conn.execute(
            "SELECT vehicle_id, user_id, vehicle_type, is_verified FROM vehicle WHERE vehicle_id = %(vid)s",
            {"vid": int(vehicle_id)},
        ).fetchone()
        if not veh:
            raise ValueError(f"ERR_VEHICLE_NOT_FOUND: vehicle {vehicle_id} does not exist")
        if int(veh["user_id"]) != int(user_id):
            raise ValueError(
                f"ERR_VEHICLE_OWNER_MISMATCH: vehicle {vehicle_id} belongs to user {veh['user_id']}, not user {user_id}"
            )
        if int(veh["is_verified"]) != 1:
            raise ValueError(f"ERR_VEHICLE_UNVERIFIED: vehicle {vehicle_id} is not KYC/RTO verified")

        vtype = veh["vehicle_type"].upper()

        # 2. Lock slot row with SELECT ... FOR UPDATE to serialize concurrent contenders
        slot = conn.execute(
            "SELECT zone_id, slot_id, lot_id, slot_type, hourly_rate, is_occupied "
            "FROM parking_slot WHERE slot_id = %(sid)s FOR UPDATE",
            {"sid": int(slot_id)},
        ).fetchone()
        if not slot:
            raise ValueError(f"ERR_SLOT_NOT_FOUND: slot {slot_id} does not exist")

        zone_id = int(slot["zone_id"])
        lot_id = int(slot["lot_id"])
        stype = slot["slot_type"].upper()

        # 3. Check lot is active
        lot = conn.execute(
            "SELECT is_active FROM parking_lot WHERE zone_id = %(zid)s AND lot_id = %(lid)s",
            {"zid": zone_id, "lid": lot_id},
        ).fetchone()
        if not lot or int(lot["is_active"]) != 1:
            raise ValueError(f"ERR_LOT_INACTIVE: parking lot {lot_id} (zone {zone_id}) is currently inactive")

        # 4. Check vehicle-slot compatibility
        if vtype == "TRUCK" and stype != "LARGE":
            raise ValueError(f"ERR_INCOMPATIBLE_SLOT: TRUCK vehicle cannot book {stype} slot (LARGE required)")
        if vtype != "EV" and stype == "EV":
            raise ValueError(f"ERR_INCOMPATIBLE_SLOT: {vtype} vehicle cannot book an EV charging slot")

        # 5. Check for overlapping booking on this slot (back-to-back where end_time == start_time is allowed)
        clash = conn.execute(
            "SELECT booking_id FROM booking "
            "WHERE slot_id = %(sid)s AND status NOT IN ('CANCELLED', 'COMPLETED') "
            "AND start_time < %(e)s AND end_time > %(b)s LIMIT 1",
            {"sid": int(slot_id), "b": start_dt, "e": end_dt},
        ).fetchone()
        if clash:
            raise ValueError(
                f"ERR_SLOT_OVERLAP: slot {slot_id} is already booked in that window (clash with booking {clash['booking_id']})"
            )

        # 6. Calculate price via fn_calc_price
        price_row = conn.execute(
            "SELECT fn_calc_price(%(sid)s::INT8, %(vt)s::STRING, %(b)s::TIMESTAMPTZ, %(e)s::TIMESTAMPTZ) AS total",
            {"sid": int(slot_id), "vt": vtype, "b": start_dt, "e": end_dt},
        ).fetchone()
        total = float(price_row["total"]) if price_row and price_row["total"] is not None else 0.0

        # 7. Insert booking
        bid_row = conn.execute("SELECT unique_rowid() AS id").fetchone()
        booking_id = int(bid_row["id"])
        conn.execute(
            "INSERT INTO booking (booking_id, user_id, vehicle_id, zone_id, slot_id, start_time, end_time, status, total_amount) "
            "VALUES (%(bid)s, %(uid)s, %(vid)s, %(zid)s, %(sid)s, %(b)s, %(e)s, 'CONFIRMED', %(tot)s)",
            {
                "bid": booking_id,
                "uid": int(user_id),
                "vid": int(vehicle_id),
                "zid": zone_id,
                "sid": int(slot_id),
                "b": start_dt,
                "e": end_dt,
                "tot": total,
            },
        )

        # 8. Insert initial payment
        pid_row = conn.execute("SELECT unique_rowid() AS id").fetchone()
        payment_id = int(pid_row["id"])
        tx_ref = f"TXN-{booking_id}-{uuid.uuid4().hex[:8].upper()}"
        conn.execute(
            "INSERT INTO payment (payment_id, booking_id, amount, payment_method, status, transaction_ref, payment_timestamp) "
            "VALUES (%(pid)s, %(bid)s, %(amt)s, %(m)s, 'SUCCESS', %(ref)s, now())",
            {
                "pid": payment_id,
                "bid": booking_id,
                "amt": total,
                "m": method.upper(),
                "ref": tx_ref,
            },
        )

        if simulate_error:
            raise RuntimeError("ERR_SIMULATED_ROLLBACK: simulated mid-transaction failure after booking+payment insert")

        return booking_id, total

    return _run_txn(_txn)


def process_exit(booking_id: int, exit_time):
    """Process vehicle exit, compute overstay & tiered penalty, insert penalty payment if > 0, and sync slot occupancy."""
    exit_dt = _norm_ts(exit_time)

    def _txn(conn):
        bk = conn.execute(
            "SELECT booking_id, user_id, zone_id, slot_id, start_time, end_time, status "
            "FROM booking WHERE booking_id = %(bid)s FOR UPDATE",
            {"bid": int(booking_id)},
        ).fetchone()
        if not bk:
            raise ValueError(f"ERR_BOOKING_NOT_FOUND: booking {booking_id} does not exist")

        log = conn.execute(
            "SELECT log_id, entry_time, exit_time FROM entry_exit_log WHERE booking_id = %(bid)s FOR UPDATE",
            {"bid": int(booking_id)},
        ).fetchone()
        if not log or log["entry_time"] is None:
            raise ValueError(f"ERR_NO_ENTRY_LOG: booking {booking_id} has no recorded entry time")
        if log["exit_time"] is not None or bk["status"] == "COMPLETED":
            raise ValueError(f"ERR_ALREADY_EXITED: exit has already been recorded for booking {booking_id}")

        entry_dt = _norm_ts(log["entry_time"])
        end_dt = _norm_ts(bk["end_time"])
        if exit_dt < entry_dt:
            raise ValueError("ERR_INVALID_EXIT_TIME: exit_time cannot be earlier than entry_time")

        duration_min = max(1, int(math.ceil((exit_dt - entry_dt).total_seconds() / 60.0)))
        overstay_min = max(0, int(math.ceil((exit_dt - end_dt).total_seconds() / 60.0))) if exit_dt > end_dt else 0

        pen_row = conn.execute("SELECT fn_penalty(%(m)s::INT8) AS pen", {"m": overstay_min}).fetchone()
        penalty = float(pen_row["pen"]) if pen_row and pen_row["pen"] is not None else 0.0

        # Update entry_exit_log
        conn.execute(
            "UPDATE entry_exit_log "
            "SET exit_time = %(ex)s, actual_duration_min = %(dur)s, overstay_min = %(ov)s, penalty_amount = %(pen)s "
            "WHERE booking_id = %(bid)s",
            {"ex": exit_dt, "dur": duration_min, "ov": overstay_min, "pen": penalty, "bid": int(booking_id)},
        )

        # Insert penalty payment if penalty > 0
        if penalty > 0:
            pid_row = conn.execute("SELECT unique_rowid() AS id").fetchone()
            tx_ref = f"PEN-{booking_id}-{uuid.uuid4().hex[:8].upper()}"
            conn.execute(
                "INSERT INTO payment (payment_id, booking_id, amount, payment_method, status, transaction_ref, payment_timestamp) "
                "VALUES (%(pid)s, %(bid)s, %(amt)s, 'UPI', 'SUCCESS', %(ref)s, now())",
                {"pid": int(pid_row["id"]), "bid": int(booking_id), "amt": penalty, "ref": tx_ref},
            )

        # Mark booking COMPLETED
        conn.execute(
            "UPDATE booking SET status = 'COMPLETED' WHERE booking_id = %(bid)s",
            {"bid": int(booking_id)},
        )

        # Occupancy sync: clear slot is_occupied only if no other ACTIVE booking exists on that slot
        other_active = conn.execute(
            "SELECT 1 FROM booking WHERE slot_id = %(sid)s AND status = 'ACTIVE' AND booking_id <> %(bid)s LIMIT 1",
            {"sid": int(bk["slot_id"]), "bid": int(booking_id)},
        ).fetchone()
        if not other_active:
            conn.execute(
                "UPDATE parking_slot SET is_occupied = 0 WHERE slot_id = %(sid)s",
                {"sid": int(bk["slot_id"])},
            )

        return {
            "booking_id": int(booking_id),
            "duration_min": duration_min,
            "overstay_min": overstay_min,
            "penalty": penalty,
        }

    return _run_txn(_txn)


def update_booking_status(booking_id: int, new_status: str):
    """Update booking status and synchronize parking_slot.is_occupied atomically."""
    new_status = new_status.upper().strip()

    def _txn(conn):
        bk = conn.execute(
            "SELECT booking_id, slot_id, start_time, status FROM booking WHERE booking_id = %(bid)s FOR UPDATE",
            {"bid": int(booking_id)},
        ).fetchone()
        if not bk:
            raise ValueError(f"ERR_BOOKING_NOT_FOUND: booking {booking_id} does not exist")

        slot_id = int(bk["slot_id"])
        conn.execute(
            "UPDATE booking SET status = %(st)s WHERE booking_id = %(bid)s",
            {"st": new_status, "bid": int(booking_id)},
        )

        if new_status == "ACTIVE":
            conn.execute("UPDATE parking_slot SET is_occupied = 1 WHERE slot_id = %(sid)s", {"sid": slot_id})
            # Ensure entry_exit_log exists when booking becomes ACTIVE
            existing_log = conn.execute(
                "SELECT log_id FROM entry_exit_log WHERE booking_id = %(bid)s",
                {"bid": int(booking_id)},
            ).fetchone()
            if not existing_log:
                lid = conn.execute("SELECT unique_rowid() AS id").fetchone()["id"]
                conn.execute(
                    "INSERT INTO entry_exit_log (log_id, booking_id, entry_time, overstay_min, penalty_amount) "
                    "VALUES (%(lid)s, %(bid)s, %(ent)s, 0, 0.00)",
                    {"lid": int(lid), "bid": int(booking_id), "ent": bk["start_time"]},
                )
        elif new_status in ("COMPLETED", "CANCELLED"):
            other_active = conn.execute(
                "SELECT 1 FROM booking WHERE slot_id = %(sid)s AND status = 'ACTIVE' AND booking_id <> %(bid)s LIMIT 1",
                {"sid": slot_id, "bid": int(booking_id)},
            ).fetchone()
            if not other_active:
                conn.execute("UPDATE parking_slot SET is_occupied = 0 WHERE slot_id = %(sid)s", {"sid": slot_id})

    return _run_txn(_txn)


def refund_payment(payment_id: int, new_status: str = "REFUNDED"):
    """Update payment status; when transitioning to REFUNDED, credit the booking owner's wallet exactly once."""
    new_status = new_status.upper().strip()

    def _txn(conn):
        pay = conn.execute(
            "SELECT p.payment_id, p.booking_id, p.amount, p.status, b.user_id "
            "FROM payment p JOIN booking b ON b.booking_id = p.booking_id "
            "WHERE p.payment_id = %(pid)s FOR UPDATE",
            {"pid": int(payment_id)},
        ).fetchone()
        if not pay:
            raise ValueError(f"ERR_PAYMENT_NOT_FOUND: payment {payment_id} does not exist")

        old_status = pay["status"]
        if old_status == "REFUNDED" and new_status == "REFUNDED":
            raise ValueError(f"ERR_ALREADY_REFUNDED: payment {payment_id} was already refunded")

        conn.execute(
            "UPDATE payment SET status = %(st)s WHERE payment_id = %(pid)s",
            {"st": new_status, "pid": int(payment_id)},
        )

        credited = False
        if new_status == "REFUNDED" and old_status != "REFUNDED":
            conn.execute(
                "UPDATE registered_user SET wallet_balance = wallet_balance + %(amt)s WHERE user_id = %(uid)s",
                {"amt": pay["amount"], "uid": int(pay["user_id"])},
            )
            credited = True

        bal_row = conn.execute(
            "SELECT wallet_balance FROM registered_user WHERE user_id = %(uid)s",
            {"uid": int(pay["user_id"])},
        ).fetchone()

        return {
            "payment_id": int(payment_id),
            "user_id": int(pay["user_id"]),
            "amount": float(pay["amount"]),
            "credited": credited,
            "new_wallet_balance": float(bal_row["wallet_balance"]) if bal_row else None,
        }

    return _run_txn(_txn)
