-- ============================================================================
-- ParkWise DA3 — Work Package B: Dataset & Constraint Validation (validate_b.sql)
-- Verifies row counts, distributions, zero slot window overlaps, zero orphan
-- payments/logs/disputes, at most one log per booking, and compatibility rules.
-- ============================================================================

-- 1. Row counts per table in Module B
SELECT 'penalty_tier' AS table_name, COUNT(*) AS row_count FROM penalty_tier
UNION ALL
SELECT 'booking', COUNT(*) FROM booking
UNION ALL
SELECT 'payment', COUNT(*) FROM payment
UNION ALL
SELECT 'entry_exit_log', COUNT(*) FROM entry_exit_log
UNION ALL
SELECT 'dispute', COUNT(*) FROM dispute
UNION ALL
SELECT 'TOTAL_MODULE_B',
       (SELECT COUNT(*) FROM penalty_tier) +
       (SELECT COUNT(*) FROM booking) +
       (SELECT COUNT(*) FROM payment) +
       (SELECT COUNT(*) FROM entry_exit_log) +
       (SELECT COUNT(*) FROM dispute);

-- 2. Booking status distribution
SELECT status AS booking_status, COUNT(*) AS count
FROM booking
GROUP BY status
ORDER BY count DESC;

-- 3. Payment status distribution
SELECT status AS payment_status, COUNT(*) AS count
FROM payment
GROUP BY status
ORDER BY count DESC;

-- 4. Entry/Exit log overstay distribution & penalty check
SELECT overstay_min, penalty_amount, COUNT(*) AS log_count
FROM entry_exit_log
GROUP BY overstay_min, penalty_amount
ORDER BY overstay_min;

-- 5. Dispute status distribution
SELECT status AS dispute_status, COUNT(*) AS count
FROM dispute
GROUP BY status
ORDER BY status;

-- 6. Integrity & Invariant Validation Checks (All must equal 0)
SELECT
    -- Check 1: No overlapping non-cancelled bookings on the same slot
    (SELECT COUNT(*)
     FROM booking b1
     JOIN booking b2
       ON b1.slot_id = b2.slot_id
      AND b1.booking_id < b2.booking_id
      AND b1.status <> 'CANCELLED'
      AND b2.status <> 'CANCELLED'
      AND b1.start_time < b2.end_time
      AND b1.end_time > b2.start_time
    ) AS overlapping_slot_bookings,

    -- Check 2: No orphan payments
    (SELECT COUNT(*)
     FROM payment p
     LEFT JOIN booking b ON b.booking_id = p.booking_id
     WHERE b.booking_id IS NULL
    ) AS orphan_payments,

    -- Check 3: No orphan entry_exit_logs
    (SELECT COUNT(*)
     FROM entry_exit_log l
     LEFT JOIN booking b ON b.booking_id = l.booking_id
     WHERE b.booking_id IS NULL
    ) AS orphan_logs,

    -- Check 4: No orphan disputes
    (SELECT COUNT(*)
     FROM dispute d
     LEFT JOIN booking b ON b.booking_id = d.booking_id
     WHERE b.booking_id IS NULL
    ) AS orphan_disputes,

    -- Check 5: At most one entry_exit_log per booking
    (SELECT COUNT(*)
     FROM (
         SELECT booking_id
         FROM entry_exit_log
         GROUP BY booking_id
         HAVING COUNT(*) > 1
     )
    ) AS duplicate_logs_per_booking,

    -- Check 6: Vehicle-Slot compatibility (no TRUCK on non-LARGE, no non-EV on EV)
    (SELECT COUNT(*)
     FROM booking b
     JOIN vehicle v ON v.vehicle_id = b.vehicle_id
     JOIN parking_slot s ON s.slot_id = b.slot_id
     WHERE (v.vehicle_type = 'TRUCK' AND s.slot_type <> 'LARGE')
        OR (v.vehicle_type <> 'EV' AND s.slot_type = 'EV')
    ) AS compatibility_violations;
