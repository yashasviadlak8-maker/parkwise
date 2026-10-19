-- ============================================================================
-- ParkWise DA3 — Work Package B: Schema Definition (01_schema.sql)
-- Module: Bookings, Consistency and Node Survival (CockroachDB)
-- ============================================================================

DROP TABLE IF EXISTS dispute CASCADE;
DROP TABLE IF EXISTS entry_exit_log CASCADE;
DROP TABLE IF EXISTS payment CASCADE;
DROP TABLE IF EXISTS booking CASCADE;
DROP TABLE IF EXISTS penalty_tier CASCADE;

-- ---------------------------------------------------------------------------
-- 1. PENALTY TIER
-- ---------------------------------------------------------------------------
CREATE TABLE penalty_tier (
    tier_id          INT8 DEFAULT unique_rowid() PRIMARY KEY,
    min_minutes      INT8 NOT NULL CHECK (min_minutes >= 0),
    max_minutes      INT8,
    flat_amount      DECIMAL(10,2) NOT NULL DEFAULT 0.00 CHECK (flat_amount >= 0),
    per_hour_amount  DECIMAL(10,2) NOT NULL DEFAULT 0.00 CHECK (per_hour_amount >= 0),
    CONSTRAINT chk_tier_bounds CHECK (max_minutes IS NULL OR max_minutes >= min_minutes)
);

-- Seed the 4 standard penalty tiers:
-- 0-15 mins: 0; 16-60 mins: flat 50; 61-180 mins: flat 150; >180 mins: flat 150 + 100/started hour
INSERT INTO penalty_tier (tier_id, min_minutes, max_minutes, flat_amount, per_hour_amount) VALUES
    (1, 0,   15,   0.00,   0.00),
    (2, 16,  60,   50.00,  0.00),
    (3, 61,  180,  150.00, 0.00),
    (4, 181, NULL, 150.00, 100.00);

-- ---------------------------------------------------------------------------
-- 2. BOOKING (Not partitioned; includes zone_id of its slot)
-- Cross-owner FKs are deferred to 99_fk_B.sql per contract.
-- ---------------------------------------------------------------------------
CREATE TABLE booking (
    booking_id       INT8 DEFAULT unique_rowid() PRIMARY KEY,
    user_id          INT8 NOT NULL,
    vehicle_id       INT8 NOT NULL,
    zone_id          INT8 NOT NULL DEFAULT 1,
    slot_id          INT8 NOT NULL,
    start_time       TIMESTAMPTZ NOT NULL,
    end_time         TIMESTAMPTZ NOT NULL,
    status           STRING DEFAULT 'CONFIRMED' CHECK (status IN ('PENDING', 'CONFIRMED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
    total_amount     DECIMAL(10,2) NOT NULL CHECK (total_amount >= 0),
    CONSTRAINT chk_book_time CHECK (end_time > start_time),
    INDEX idx_booking_slot_window (slot_id, status, start_time, end_time),
    INDEX idx_booking_zone_slot (zone_id, slot_id)
);

-- ---------------------------------------------------------------------------
-- 3. PAYMENT (FK to booking, UNIQUE transaction_ref)
-- ---------------------------------------------------------------------------
CREATE TABLE payment (
    payment_id          INT8 DEFAULT unique_rowid() PRIMARY KEY,
    booking_id          INT8 NOT NULL,
    amount              DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
    payment_method      STRING DEFAULT 'UPI' CHECK (payment_method IN ('UPI', 'CARD', 'WALLET', 'CASH')),
    status              STRING DEFAULT 'SUCCESS' CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'REFUNDED')),
    transaction_ref     STRING UNIQUE,
    payment_timestamp   TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_pay_booking FOREIGN KEY (booking_id) REFERENCES booking(booking_id) ON DELETE CASCADE,
    INDEX idx_payment_booking (booking_id)
);

-- ---------------------------------------------------------------------------
-- 4. ENTRY / EXIT LOG (FK to booking, UNIQUE booking_id)
-- ---------------------------------------------------------------------------
CREATE TABLE entry_exit_log (
    log_id              INT8 DEFAULT unique_rowid() PRIMARY KEY,
    booking_id          INT8 NOT NULL UNIQUE,
    entry_time          TIMESTAMPTZ,
    exit_time           TIMESTAMPTZ,
    actual_duration_min INT8,
    overstay_min        INT8 DEFAULT 0 CHECK (overstay_min >= 0),
    penalty_amount      DECIMAL(10,2) DEFAULT 0.00 CHECK (penalty_amount >= 0),
    CONSTRAINT fk_log_booking FOREIGN KEY (booking_id) REFERENCES booking(booking_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 5. DISPUTE (FK to booking; raised_by FK deferred to 99_fk_B.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE dispute (
    dispute_id          INT8 DEFAULT unique_rowid() PRIMARY KEY,
    booking_id          INT8 NOT NULL,
    raised_by           INT8 NOT NULL,
    status              STRING DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'UNDER_REVIEW', 'RESOLVED', 'REJECTED')),
    resolution_notes    STRING,
    created_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_disp_booking FOREIGN KEY (booking_id) REFERENCES booking(booking_id) ON DELETE CASCADE,
    INDEX idx_dispute_booking (booking_id)
);
