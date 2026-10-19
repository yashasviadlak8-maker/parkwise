"""Work Package B — Demo D3: Concurrent Booking & Serializable Isolation (concurrent_booking.py).

Phase 1 (Contention Test — 100 threads, SAME slot & window):
  - 100 threads concurrently call book_slot() for slot_id=1 on 2027-02-01 10:00..12:00 UTC.
  - Expected: Exactly 1 booking succeeds, 99 are rejected cleanly (ERR_SLOT_OVERLAP),
    and the retry loop handles any SQLSTATE 40001 SerializationFailure transparently.

Phase 2 (Throughput Test — 100 threads, 100 DIFFERENT slots):
  - 100 threads concurrently call book_slot() across 100 distinct STANDARD slots on 2027-02-02 10:00..12:00 UTC.
  - Expected: All 100 bookings succeed (100 succeeded, 0 rejected).
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CRDB_URL", "postgresql://root@127.0.0.1:26257/parkwise?sslmode=disable")
os.environ["CRDB_URL"] = os.environ["CRDB_URL"].replace("@localhost:", "@127.0.0.1:")

from core import crdb, booking_crdb


def run_demo_d3():
    print("=" * 80)
    print("DEMO D3: CONCURRENT BOOKING UNDER COCKROACHDB SERIALIZABLE ISOLATION")
    print("=" * 80)

    # Clean up any previous D3 test rows in Feb 2027
    crdb.execute("DELETE FROM booking WHERE start_time >= '2027-02-01T00:00:00Z' AND start_time < '2027-03-01T00:00:00Z'")

    # -------------------------------------------------------------------------
    # PHASE 1: 100 Threads Competing for the SAME Slot & Time Window
    # -------------------------------------------------------------------------
    target_slot = 1  # STANDARD slot in Lot 1 (Zone 1)
    p1_start = datetime(2027, 2, 1, 10, 0, tzinfo=timezone.utc)
    p1_end = datetime(2027, 2, 1, 12, 0, tzinfo=timezone.utc)

    print(f"\n[PHASE 1] Launching 100 concurrent threads for Slot #{target_slot} ({p1_start.isoformat()} -> {p1_end.isoformat()})...")

    def _worker_same_slot(tid: int):
        # Users 1..100 own Vehicles 1..100 (all verified CARs)
        uid = tid
        vid = tid
        try:
            bid, total = booking_crdb._run_txn(
                lambda conn: _book_inner_with_high_retry(uid, vid, target_slot, p1_start, p1_end),
                tries=15,
            )
            return ("SUCCESS", tid, bid, total)
        except ValueError as e:
            if "ERR_SLOT_OVERLAP" in str(e):
                return ("REJECTED_OVERLAP", tid, None, str(e))
            return ("ERROR", tid, None, str(e))
        except Exception as e:
            return ("ERROR", tid, None, str(e))

    # Note: we call booking_crdb.book_slot directly (increasing tries=15 inside book_slot for 100-way contention)
    t0 = time.perf_counter()
    p1_results = []
    with ThreadPoolExecutor(max_workers=100) as pool:
        futures = [
            pool.submit(_call_book_slot_with_retries, tid, tid, target_slot, p1_start, p1_end)
            for tid in range(1, 101)
        ]
        for fut in as_completed(futures):
            p1_results.append(fut.result())
    p1_elapsed = time.perf_counter() - t0

    successes_p1 = [r for r in p1_results if r[0] == "SUCCESS"]
    overlaps_p1 = [r for r in p1_results if r[0] == "REJECTED_OVERLAP"]
    errors_p1 = [r for r in p1_results if r[0] == "ERROR"]

    db_count_p1 = crdb.query(
        "SELECT COUNT(*) AS n FROM booking WHERE slot_id = :s AND start_time = :b",
        {"s": target_slot, "b": p1_start},
    )[0]["n"]

    print(f"  Completed in         : {p1_elapsed:.2f} seconds")
    print(f"  Succeeded bookings   : {len(successes_p1)} (Winner: Thread #{successes_p1[0][1]}, Booking ID #{successes_p1[0][2]})" if successes_p1 else "  Succeeded bookings   : 0")
    print(f"  Cleanly rejected     : {len(overlaps_p1)} (ERR_SLOT_OVERLAP)")
    print(f"  Unexpected errors    : {len(errors_p1)}")
    print(f"  DB verification count: {db_count_p1} row(s) persisted in booking table for Slot #{target_slot}")

    # -------------------------------------------------------------------------
    # PHASE 2: 100 Threads Booking 100 DIFFERENT Slots Concurrently
    # -------------------------------------------------------------------------
    # Collect first 100 STANDARD slots across active lots (slots where ((s-1)%50)+1 <= 30)
    distinct_slots = [s for s in range(1, 250) if ((s - 1) % 50) + 1 <= 30][:100]
    p2_start = datetime(2027, 2, 2, 10, 0, tzinfo=timezone.utc)
    p2_end = datetime(2027, 2, 2, 12, 0, tzinfo=timezone.utc)

    print(f"\n[PHASE 2] Launching 100 concurrent threads across 100 DISTINCT slots ({p2_start.isoformat()} -> {p2_end.isoformat()})...")

    t1 = time.perf_counter()
    p2_results = []
    with ThreadPoolExecutor(max_workers=100) as pool:
        futures = [
            pool.submit(_call_book_slot_with_retries, idx + 1, idx + 1, slot_id, p2_start, p2_end)
            for idx, slot_id in enumerate(distinct_slots)
        ]
        for fut in as_completed(futures):
            p2_results.append(fut.result())
    p2_elapsed = time.perf_counter() - t1

    successes_p2 = [r for r in p2_results if r[0] == "SUCCESS"]
    overlaps_p2 = [r for r in p2_results if r[0] == "REJECTED_OVERLAP"]
    errors_p2 = [r for r in p2_results if r[0] == "ERROR"]

    db_count_p2 = crdb.query(
        "SELECT COUNT(*) AS n FROM booking WHERE start_time = :b",
        {"b": p2_start},
    )[0]["n"]

    print(f"  Completed in         : {p2_elapsed:.2f} seconds")
    print(f"  Succeeded bookings   : {len(successes_p2)} / 100")
    print(f"  Rejected bookings    : {len(overlaps_p2)}")
    print(f"  Unexpected errors    : {len(errors_p2)}")
    print(f"  DB verification count: {db_count_p2} row(s) persisted in booking table")

    # Clean up Feb 2027 demo rows so dataset counts remain exact
    crdb.execute("DELETE FROM booking WHERE start_time >= '2027-02-01T00:00:00Z' AND start_time < '2027-03-01T00:00:00Z'")
    print("\n" + "=" * 80)
    print("DEMO D3 COMPLETED SUCCESSFULLY!")
    print("=" * 80)


def _call_book_slot_with_retries(uid: int, vid: int, slot_id: int, start_dt, end_dt):
    try:
        bid, total = booking_crdb.book_slot(uid, vid, slot_id, start_dt, end_dt, "UPI")
        return ("SUCCESS", uid, bid, total)
    except ValueError as e:
        if "ERR_SLOT_OVERLAP" in str(e):
            return ("REJECTED_OVERLAP", uid, None, str(e))
        return ("ERROR", uid, None, str(e))
    except Exception as e:
        return ("ERROR", uid, None, str(e))


if __name__ == "__main__":
    run_demo_d3()
