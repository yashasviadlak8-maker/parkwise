-- ============================================================================
-- ParkWise DA3: Work Package C — Standalone Testing Stubs
-- Parent tables owned by Package A (Infrastructure) and Package B (Bookings)
-- Required strictly for standalone testing of Package C business logic
-- (zone_monthly_revenue and parking_attendant foreign key).
--
-- Integration & Reconciliation Contract:
--   - These stub tables contain minimal columns strictly for standalone testing.
--   - On merge day, these stubs must be reconciled and replaced by the full schemas
--     owned by Person A (zone_config, parking_lot, parking_slot with partitioning)
--     and Person B (booking, payment with full transaction attributes).
--   - Drop these stubs prior to running real Package A and B schemas at integration.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Stub: zone_config (Owned by Package A)
-- Fixed IDs: 1 NORTH, 2 SOUTH, 3 EAST, 4 WEST, 5 CENTRAL
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zone_config (
    zone_id          INT8 PRIMARY KEY,
    zone_name        STRING(50) NOT NULL UNIQUE
);

UPSERT INTO zone_config (zone_id, zone_name) VALUES
    (1, 'NORTH'),
    (2, 'SOUTH'),
    (3, 'EAST'),
    (4, 'WEST'),
    (5, 'CENTRAL');

-- ---------------------------------------------------------------------------
-- 2. Stub: parking_lot (Owned by Package A)
-- Composite PK: (zone_id, lot_id) partitioned by zone_id in Package A.
-- Seed rule: lot l is in zone ((l - 1) DIV 10) + 1 for lots 1-50.
-- Required for parking_attendant(zone_id, lot_id) FK testing.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parking_lot (
    zone_id          INT8 NOT NULL,
    lot_id           INT8 NOT NULL,
    PRIMARY KEY (zone_id, lot_id),
    CONSTRAINT fk_stub_lot_zone FOREIGN KEY (zone_id) REFERENCES zone_config(zone_id) ON DELETE CASCADE
);

INSERT INTO parking_lot (zone_id, lot_id)
SELECT FLOOR((i - 1)::DECIMAL / 10)::INT8 + 1, i
FROM generate_series(1, 50) AS s(i)
ON CONFLICT (zone_id, lot_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Stub: parking_slot (Owned by Package A)
-- Composite PK: (zone_id, slot_id) with composite FK (zone_id, lot_id) to parking_lot.
-- Required for joining revenue from payment -> booking -> slot -> lot -> zone.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parking_slot (
    zone_id          INT8 NOT NULL,
    slot_id          INT8 NOT NULL,
    lot_id           INT8 NOT NULL,
    PRIMARY KEY (zone_id, slot_id),
    CONSTRAINT fk_stub_slot_lot FOREIGN KEY (zone_id, lot_id) REFERENCES parking_lot(zone_id, lot_id) ON DELETE CASCADE
);

UPSERT INTO parking_slot (zone_id, slot_id, lot_id) VALUES
    (1, 1, 1),
    (1, 2, 1),
    (1, 3, 2),
    (2, 501, 11),
    (2, 502, 12),
    (3, 1001, 21),
    (3, 1002, 22),
    (4, 1501, 31),
    (4, 1502, 32);
-- Note: Zone 5 intentionally has no slots in this stub to test empty revenue handling.

-- ---------------------------------------------------------------------------
-- 4. Stub: booking (Owned by Package B)
-- Includes zone_id (zone of its slot) per DA3 contract.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS booking (
    booking_id       INT8 PRIMARY KEY,
    zone_id          INT8 NOT NULL,
    slot_id          INT8 NOT NULL,
    CONSTRAINT fk_stub_book_slot FOREIGN KEY (zone_id, slot_id) REFERENCES parking_slot(zone_id, slot_id) ON DELETE CASCADE
);

UPSERT INTO booking (booking_id, zone_id, slot_id) VALUES
    (1, 1, 1),
    (2, 1, 2),
    (3, 1, 3),
    (4, 2, 501),
    (5, 2, 502),
    (6, 3, 1001),
    (7, 3, 1002),
    (8, 4, 1501),
    (9, 4, 1502),
    (10, 1, 1);

-- ---------------------------------------------------------------------------
-- 5. Stub: payment (Owned by Package B)
-- Hand-made sample rows for testing zone_monthly_revenue edge cases:
-- - SUCCESS payments
-- - REFUNDED payment deducted
-- - FAILED / PENDING payments excluded
-- - Payments in other months excluded
-- - Zone with no payments returns 0
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment (
    payment_id          INT8 PRIMARY KEY,
    booking_id          INT8 NOT NULL,
    amount              DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
    status              STRING(20) DEFAULT 'SUCCESS' CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'REFUNDED')),
    payment_timestamp   TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_stub_pay_book FOREIGN KEY (booking_id) REFERENCES booking(booking_id) ON DELETE CASCADE
);

UPSERT INTO payment (payment_id, booking_id, amount, status, payment_timestamp) VALUES
    -- Zone 1 (NORTH) in October 2026: Success (100 + 150) - Refunded (50) = Net 200.00
    (1, 1, 100.00, 'SUCCESS',  '2026-10-05 10:00:00+00'),
    (2, 2, 150.00, 'SUCCESS',  '2026-10-10 14:00:00+00'),
    (3, 3,  50.00, 'REFUNDED', '2026-10-12 16:00:00+00'),
    (4, 10, 80.00, 'FAILED',   '2026-10-14 09:00:00+00'),
    (5, 1,  70.00, 'SUCCESS',  '2026-09-20 11:00:00+00'), -- Prior month: excluded from Oct 2026
    -- Zone 2 (SOUTH) in October 2026: Success (120 + 180) = Net 300.00
    (6, 4, 120.00, 'SUCCESS',  '2026-10-08 12:00:00+00'),
    (7, 5, 180.00, 'SUCCESS',  '2026-10-18 15:00:00+00'),
    -- Zone 3 (EAST) in October 2026: Success (250) - Refunded (40) = Net 210.00
    (8, 6, 250.00, 'SUCCESS',  '2026-10-15 16:30:00+00'),
    (9, 7,  40.00, 'REFUNDED', '2026-10-16 11:00:00+00'),
    -- Zone 4 (WEST) in October 2026: Only pending in Oct (excluded) and past success = Net 0.00
    (10, 8, 60.00, 'PENDING',  '2026-10-17 18:00:00+00'),
    (11, 9, 90.00, 'SUCCESS',  '2026-08-11 10:00:00+00');
    -- Zone 5 (CENTRAL): No payments at all (Net 0.00)

-- ============================================================================
-- Standalone Cleanup Helper:
--   Before merging with Package A and B schemas, run the following statement to
--   cleanly drop these testing stubs without affecting Package C tables:
--
--   DROP TABLE IF EXISTS payment, booking, parking_slot, parking_lot, zone_config CASCADE;
-- ============================================================================
