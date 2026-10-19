"""Work Package B — Deterministic Data Generator & Loader (generate_b.py).

Generates CSV datasets with fixed seed (42) and loads them into CockroachDB via COPY:
  - 4,000 bookings (ids 1..4000), zero slot overlaps, strict vehicle-owner and slot-type compatibility
  - 4,120 payments (ids 1..4120), including FAILED (with 120 SUCCESS retries) and REFUNDED
  - 3,000 entry_exit_logs (ids 1..3000) for COMPLETED (2,200) and ACTIVE (800) bookings,
    with overstays in {0, 10, 20, 90, 240} minutes
  - 200 disputes (ids 1..200) across all 4 statuses (OPEN, UNDER_REVIEW, RESOLVED, REJECTED)
  Total rows generated & loaded in Module B: 11,324 (including 4 penalty_tier rows).
"""
import csv
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import psycopg

SEED = 42
DATA_DIR = Path(__file__).resolve().parent


def slot_info(slot_id: int):
    """Return (zone_id, lot_id, slot_type, hourly_rate) per shared contract rules."""
    zone_id = ((slot_id - 1) // 500) + 1
    lot_id = ((slot_id - 1) // 50) + 1
    pos = ((slot_id - 1) % 50) + 1
    if pos <= 30:
        return zone_id, lot_id, "STANDARD", 40.00
    elif pos <= 38:
        return zone_id, lot_id, "COMPACT", 30.00
    elif pos <= 46:
        return zone_id, lot_id, "LARGE", 60.00
    else:
        return zone_id, lot_id, "EV", 80.00


def vehicle_owner(vehicle_id: int) -> int:
    """Owner of vehicle v is user ((v-1) MOD 1400) + 1."""
    return ((vehicle_id - 1) % 1400) + 1


def calc_penalty(overstay_min: int) -> float:
    """Exact match to penalty_tier & fn_penalty."""
    if overstay_min <= 15:
        return 0.00
    if overstay_min <= 60:
        return 50.00
    if overstay_min <= 180:
        return 150.00
    extra_hours = (overstay_min - 180 + 59) // 60
    return round(150.00 + 100.00 * extra_hours, 2)


def generate_csvs():
    rng = random.Random(SEED)

    # Verified vehicle pools per type (vehicles 1..1950 are verified in 00_stubs_b.sql)
    cars = list(range(1, 1001))
    bikes = list(range(1001, 1501))
    trucks = list(range(1501, 1701))
    evs = list(range(1701, 1951))

    compat_vehicles = {
        "STANDARD": cars + bikes,
        "COMPACT": bikes + cars[:300],
        "LARGE": trucks + cars[:200],
        "EV": evs,
    }

    # Status distribution for 4,000 bookings:
    # 2,200 COMPLETED (55%) + 800 ACTIVE (20%) = 3,000 with entry_exit_log
    # + 450 CONFIRMED + 300 CANCELLED + 250 PENDING = 4,000 total
    statuses = (
        ["COMPLETED"] * 2200
        + ["ACTIVE"] * 800
        + ["CONFIRMED"] * 450
        + ["CANCELLED"] * 300
        + ["PENDING"] * 250
    )
    rng.shuffle(statuses)

    # Track next non-overlapping start time per slot (slots 1..2450 in active lots 1..49)
    base_time = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)
    slot_next_start = {s: base_time + timedelta(hours=rng.randint(0, 12)) for s in range(1, 2451)}
    active_used_slots = set()

    bookings = []
    payments = []
    logs = []
    disputes = []

    methods = ["UPI", "CARD", "WALLET", "CASH"]
    overstay_choices = [0, 0, 0, 10, 20, 90, 240]

    for bid in range(1, 4001):
        status = statuses[bid - 1]

        # Pick an active slot (1..2450); ensure each ACTIVE booking sits on a distinct slot
        if status == "ACTIVE":
            while True:
                sid = rng.randint(1, 2450)
                if sid not in active_used_slots:
                    active_used_slots.add(sid)
                    break
        else:
            sid = ((bid - 1) % 2450) + 1

        zone_id, lot_id, stype, rate = slot_info(sid)
        vid = rng.choice(compat_vehicles[stype])
        uid = vehicle_owner(vid)

        duration_hrs = rng.choice([1, 2, 3, 4])
        start_dt = slot_next_start[sid]
        end_dt = start_dt + timedelta(hours=duration_hrs)
        # Advance next available window on this slot by duration + 8..16 hours gap (guarantees zero overlap)
        slot_next_start[sid] = end_dt + timedelta(hours=rng.randint(8, 16))

        total_amount = round(rate * duration_hrs, 2)

        bookings.append({
            "booking_id": bid,
            "user_id": uid,
            "vehicle_id": vid,
            "zone_id": zone_id,
            "slot_id": sid,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "status": status,
            "total_amount": f"{total_amount:.2f}",
        })

    # Generate Payments (~4,120 rows)
    # 1..4000 primary payments + 120 retry SUCCESS payments for FAILED ones
    pid = 1
    failed_Retry_candidates = []
    for b in bookings:
        bid = b["booking_id"]
        st = b["status"]
        method = rng.choice(methods)
        pay_ts = datetime.fromisoformat(b["start_time"]) - timedelta(minutes=15)

        if st == "CANCELLED":
            p_status = "REFUNDED" if (bid % 2 == 0) else "FAILED"
        elif st == "PENDING":
            p_status = "PENDING"
        else:
            # Make ~150 payments initially FAILED, of which 120 get a SUCCESS retry
            if len(failed_Retry_candidates) < 150 and (bid % 25 == 0):
                p_status = "FAILED"
                failed_Retry_candidates.append((b, method, pay_ts))
            else:
                p_status = "SUCCESS"

        payments.append({
            "payment_id": pid,
            "booking_id": bid,
            "amount": b["total_amount"],
            "payment_method": method,
            "status": p_status,
            "transaction_ref": f"TXN-{pid:06d}",
            "payment_timestamp": pay_ts.isoformat(),
        })
        pid += 1

    # Add 120 retry SUCCESS payments for the first 120 FAILED bookings
    for b, method, pay_ts in failed_Retry_candidates[:120]:
        retry_ts = pay_ts + timedelta(minutes=3)
        payments.append({
            "payment_id": pid,
            "booking_id": b["booking_id"],
            "amount": b["total_amount"],
            "payment_method": method,
            "status": "SUCCESS",
            "transaction_ref": f"TXN-RETRY-{pid:06d}",
            "payment_timestamp": retry_ts.isoformat(),
        })
        pid += 1

    # Generate 3,000 Entry/Exit Logs for all 2,200 COMPLETED and 800 ACTIVE bookings
    lid = 1
    for b in bookings:
        st = b["status"]
        if st not in ("COMPLETED", "ACTIVE"):
            continue
        start_dt = datetime.fromisoformat(b["start_time"])
        end_dt = datetime.fromisoformat(b["end_time"])
        entry_dt = start_dt + timedelta(minutes=rng.randint(0, 5))

        if st == "COMPLETED":
            overstay = rng.choice(overstay_choices)
            if overstay == 0:
                exit_dt = end_dt - timedelta(minutes=rng.randint(0, 10))
                if exit_dt <= entry_dt:
                    exit_dt = end_dt
            else:
                exit_dt = end_dt + timedelta(minutes=overstay)
            actual_dur = max(1, int((exit_dt - entry_dt).total_seconds() // 60))
            penalty = calc_penalty(overstay)
            logs.append({
                "log_id": lid,
                "booking_id": b["booking_id"],
                "entry_time": entry_dt.isoformat(),
                "exit_time": exit_dt.isoformat(),
                "actual_duration_min": str(actual_dur),
                "overstay_min": str(overstay),
                "penalty_amount": f"{penalty:.2f}",
            })
        else:
            # ACTIVE booking: currently parked (exit_time is NULL)
            logs.append({
                "log_id": lid,
                "booking_id": b["booking_id"],
                "entry_time": entry_dt.isoformat(),
                "exit_time": "",
                "actual_duration_min": "",
                "overstay_min": "0",
                "penalty_amount": "0.00",
            })
        lid += 1

    # Generate 200 Disputes across all 4 statuses
    dispute_statuses = ["OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"]
    notes_map = {
        "OPEN": "Customer reported sensor delay at entry barrier.",
        "UNDER_REVIEW": "Checking CCTV and lot attendant shift logs.",
        "RESOLVED": "Verified overstay calculation; partial credit issued to wallet.",
        "REJECTED": "Gate timestamp matches ANPR camera log; charge upheld.",
    }
    sample_bookings = bookings[:200]
    for did, b in enumerate(sample_bookings, start=1):
        d_status = dispute_statuses[(did - 1) % 4]
        created_dt = datetime.fromisoformat(b["end_time"]) + timedelta(hours=1)
        disputes.append({
            "dispute_id": did,
            "booking_id": b["booking_id"],
            "raised_by": b["user_id"],
            "status": d_status,
            "resolution_notes": notes_map[d_status],
            "created_at": created_dt.isoformat(),
        })

    def _write_csv(filename, fieldnames, rows):
        path = DATA_DIR / filename
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    b_csv = _write_csv(
        "bookings.csv",
        ["booking_id", "user_id", "vehicle_id", "zone_id", "slot_id", "start_time", "end_time", "status", "total_amount"],
        bookings,
    )
    p_csv = _write_csv(
        "payments.csv",
        ["payment_id", "booking_id", "amount", "payment_method", "status", "transaction_ref", "payment_timestamp"],
        payments,
    )
    l_csv = _write_csv(
        "entry_exit_logs.csv",
        ["log_id", "booking_id", "entry_time", "exit_time", "actual_duration_min", "overstay_min", "penalty_amount"],
        logs,
    )
    d_csv = _write_csv(
        "disputes.csv",
        ["dispute_id", "booking_id", "raised_by", "status", "resolution_notes", "created_at"],
        disputes,
    )

    print(f"Generated CSVs in {DATA_DIR}:")
    print(f"  bookings.csv        : {len(bookings)} rows")
    print(f"  payments.csv        : {len(payments)} rows")
    print(f"  entry_exit_logs.csv : {len(logs)} rows")
    print(f"  disputes.csv        : {len(disputes)} rows")
    return b_csv, p_csv, l_csv, d_csv


def load_into_crdb(b_csv, p_csv, l_csv, d_csv):
    crdb_url = os.getenv("CRDB_URL", "postgresql://root@localhost:26257/parkwise?sslmode=disable")
    with psycopg.connect(crdb_url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE dispute, entry_exit_log, payment, booking CASCADE")

            with open(b_csv, "r", encoding="utf-8") as f:
                with cur.copy(
                    "COPY booking (booking_id, user_id, vehicle_id, zone_id, slot_id, start_time, end_time, status, total_amount) "
                    "FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
                ) as copy:
                    copy.write(f.read())

            with open(p_csv, "r", encoding="utf-8") as f:
                with cur.copy(
                    "COPY payment (payment_id, booking_id, amount, payment_method, status, transaction_ref, payment_timestamp) "
                    "FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
                ) as copy:
                    copy.write(f.read())

            with open(l_csv, "r", encoding="utf-8") as f:
                with cur.copy(
                    "COPY entry_exit_log (log_id, booking_id, entry_time, exit_time, actual_duration_min, overstay_min, penalty_amount) "
                    "FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '')"
                ) as copy:
                    copy.write(f.read())

            with open(d_csv, "r", encoding="utf-8") as f:
                with cur.copy(
                    "COPY dispute (dispute_id, booking_id, raised_by, status, resolution_notes, created_at) "
                    "FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
                ) as copy:
                    copy.write(f.read())

            # Sync parking_slot.is_occupied for ACTIVE bookings
            cur.execute("UPDATE parking_slot SET is_occupied = 0 WHERE is_occupied <> 0")
            cur.execute(
                "UPDATE parking_slot SET is_occupied = 1 "
                "WHERE slot_id IN (SELECT slot_id FROM booking WHERE status = 'ACTIVE')"
            )
        conn.commit()
    print("Loaded all CSV datasets into CockroachDB via COPY successfully!")


if __name__ == "__main__":
    csv_paths = generate_csvs()
    load_into_crdb(*csv_paths)
