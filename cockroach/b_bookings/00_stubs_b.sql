-- ============================================================================
-- ParkWise DA3 — Work Package B: Standalone-Testing Stubs ONLY
-- DO NOT run this file on the integrated/team database.
-- Its minimal user_master, registered_user, and vehicle definitions are
-- fallback contracts for isolated testing, not the Package C schema.
-- Package A owns parking_lot and parking_slot; this file does not define them.
-- Never drop or seed shared tables here.
-- ============================================================================

-- Shared tables: create minimal stubs only when absent.
-- Existing Package C tables are never replaced or reseeded.
CREATE TABLE IF NOT EXISTS user_master (
    user_id INT8 PRIMARY KEY,
    user_type STRING NOT NULL
);

CREATE TABLE IF NOT EXISTS registered_user (
    user_id INT8 PRIMARY KEY,
    wallet_balance DECIMAL(10,2) DEFAULT 0.00 CHECK (wallet_balance >= 0.00)
);

CREATE TABLE IF NOT EXISTS vehicle (
    vehicle_id INT8 PRIMARY KEY,
    user_id INT8 NOT NULL,
    vehicle_type STRING NOT NULL CHECK (vehicle_type IN ('CAR', 'BIKE', 'TRUCK', 'EV')),
    is_verified INT2 DEFAULT 0 CHECK (is_verified IN (0, 1)),
    UNIQUE (vehicle_id, user_id)
);

-- Package A owns parking_lot and parking_slot.
-- This script intentionally does not create, drop, or seed those tables.
-- Load Package A's schema before running Package B's foreign-key script.

-- No shared parent data is seeded here.
-- Use Package C's generator/loader for user_master, registered_user, and vehicle.
-- Do not use these minimal fallback definitions on an integrated database.

-- Stand-in fn_calc_price for solo testing.
CREATE OR REPLACE FUNCTION fn_calc_price(
    p_slot_id INT8,
    p_vehicle_type STRING,
    p_start TIMESTAMPTZ,
    p_end TIMESTAMPTZ
) RETURNS DECIMAL(10,2)
LANGUAGE SQL
AS $$
    SELECT ROUND(
        s.hourly_rate * GREATEST(
            1::DECIMAL,
            CEIL(EXTRACT(EPOCH FROM (p_end - p_start))::DECIMAL / 3600.0)
        ),
        2
    )
    FROM parking_slot s
    WHERE s.slot_id = p_slot_id
    LIMIT 1;
$$;
