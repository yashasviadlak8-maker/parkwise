-- ============================================================================
-- ParkWise DA3 — Work Package B: SQL Functions & Logic Contract (03_logic.sql)
-- Implements fn_penalty(p_overstay_min INT8) RETURNS DECIMAL reading penalty_tier,
-- plus stand-in fn_calc_price if Module A's function is not yet loaded.
-- Multi-statement serializable transactions (book_slot, process_exit,
-- refund_payment, update_booking_status) live in core/booking_crdb.py with
-- client-side 40001 SerializationFailure retry loops.
-- ============================================================================

-- 1. fn_penalty(p_overstay_min INT8) RETURNS DECIMAL (Owned by Module B)
-- Reads penalty_tier table:
--   0..15 mins   -> 0.00
--   16..60 mins  -> 50.00
--   61..180 mins -> 150.00
--   >180 mins    -> 150.00 + 100.00 * CEIL((p_overstay_min - 180) / 60.0)
CREATE OR REPLACE FUNCTION fn_penalty(p_overstay_min INT8)
RETURNS DECIMAL(10,2)
LANGUAGE SQL
AS $$
    SELECT CASE
        WHEN p_overstay_min <= 0 THEN 0.00::DECIMAL(10,2)
        ELSE COALESCE(
            (
                SELECT ROUND(
                    t.flat_amount +
                    CASE
                        WHEN t.per_hour_amount > 0 AND p_overstay_min > 180
                        THEN t.per_hour_amount * CEIL((p_overstay_min - 180)::DECIMAL / 60.0)
                        ELSE 0.00
                    END,
                    2
                )
                FROM penalty_tier t
                WHERE p_overstay_min >= t.min_minutes
                  AND (t.max_minutes IS NULL OR p_overstay_min <= t.max_minutes)
                ORDER BY t.min_minutes DESC
                LIMIT 1
            ),
            0.00::DECIMAL(10,2)
        )
    END;
$$;
