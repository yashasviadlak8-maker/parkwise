-- ============================================================================
-- ParkWise DA3: Work Package C — CockroachDB DDL Schema Script
-- Module: Users, Vehicles, Specialization Hierarchies
-- Target Database: CockroachDB (Cloud-Native Distributed SQL)
--
-- Tables Owned (9 tables):
--   1. user_master          (User supertype)
--   2. registered_user      (Subtype: registered customer with wallet)
--   3. admin_user           (Subtype: administrator)
--   4. parking_attendant    (Subtype: lot attendant with zone_id & lot_id)
--   5. vehicle              (Vehicle supertype)
--   6. vehicle_car          (Subtype: car attributes)
--   7. vehicle_bike         (Subtype: motorcycle/scooter attributes)
--   8. vehicle_truck        (Subtype: truck/heavy vehicle attributes)
--   9. vehicle_ev           (Subtype: electric vehicle attributes)
--
-- Cross-Module Foreign Keys:
--   - Outgoing: parking_attendant (zone_id, lot_id) -> parking_lot(zone_id, lot_id)
--     Deferred to 99_fk_C.sql as per shared contract.
--   - Incoming dependencies supported:
--     * vehicle has UNIQUE (vehicle_id, user_id) for Package B's booking FK.
--     * registered_user has user_id INT8 PK for Package B's user FK.
--     * admin_user has user_id INT8 PK for Package A's parking_lot manager FK.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. USER MANAGEMENT (EER Specialization Hierarchy)
-- ---------------------------------------------------------------------------

-- Supertype table for all platform users
CREATE TABLE IF NOT EXISTS user_master (
    user_id          INT8 PRIMARY KEY DEFAULT unique_rowid(),
    phone            STRING(20) NOT NULL UNIQUE,
    email            STRING(100) NOT NULL UNIQUE,
    password_hash    STRING(255) DEFAULT 'default_hash',
    created_at       TIMESTAMPTZ DEFAULT now(),
    user_type        STRING(30) DEFAULT 'REGISTERED' CHECK (user_type IN ('REGISTERED', 'ATTENDANT', 'ADMIN'))
);

-- Subtype table: Registered end-users (customers)
CREATE TABLE IF NOT EXISTS registered_user (
    user_id                INT8 PRIMARY KEY,
    kyc_status             STRING(20) DEFAULT 'PENDING' CHECK (kyc_status IN ('PENDING', 'VERIFIED', 'REJECTED')),
    wallet_balance         DECIMAL(10,2) DEFAULT 0.00 CHECK (wallet_balance >= 0.00),
    default_payment_method STRING(20) DEFAULT 'UPI' CHECK (default_payment_method IN ('UPI', 'CARD', 'WALLET', 'CASH')),
    CONSTRAINT fk_reg_user FOREIGN KEY (user_id) REFERENCES user_master(user_id) ON DELETE CASCADE
);

-- Subtype table: Administrative staff
CREATE TABLE IF NOT EXISTS admin_user (
    user_id          INT8 PRIMARY KEY,
    department       STRING(50) NOT NULL,
    access_level     STRING(20) DEFAULT 'LEVEL_1',
    last_login       TIMESTAMPTZ,
    CONSTRAINT fk_admin_user FOREIGN KEY (user_id) REFERENCES user_master(user_id) ON DELETE CASCADE
);

-- Subtype table: Parking attendants assigned to lots
-- Note: zone_id is added adjacent to lot_id to support Package A composite key.
-- Foreign key to parking_lot(zone_id, lot_id) is isolated in 99_fk_C.sql.
CREATE TABLE IF NOT EXISTS parking_attendant (
    user_id          INT8 PRIMARY KEY,
    zone_id          INT8,
    lot_id           INT8,
    shift_start      STRING(10),
    shift_end        STRING(10),
    is_active        INT2 DEFAULT 1 CHECK (is_active IN (0, 1)),
    CONSTRAINT fk_attendant_user FOREIGN KEY (user_id) REFERENCES user_master(user_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 2. VEHICLE MANAGEMENT (EER Specialization Hierarchy)
-- ---------------------------------------------------------------------------

-- Supertype table: Vehicles registered by customers
-- Note: UNIQUE (vehicle_id, user_id) is explicitly defined because Package B's
-- booking table depends on this composite foreign key contract.
CREATE TABLE IF NOT EXISTS vehicle (
    vehicle_id       INT8 PRIMARY KEY DEFAULT unique_rowid(),
    user_id          INT8 NOT NULL,
    license_plate    STRING(30) NOT NULL UNIQUE,
    registration_date DATE DEFAULT current_date(),
    is_verified      INT2 DEFAULT 0 CHECK (is_verified IN (0, 1)),
    vehicle_type     STRING(20) DEFAULT 'CAR' CHECK (vehicle_type IN ('CAR', 'BIKE', 'TRUCK', 'EV')),
    CONSTRAINT fk_vehicle_user FOREIGN KEY (user_id) REFERENCES registered_user(user_id) ON DELETE CASCADE,
    CONSTRAINT unq_vehicle_user UNIQUE (vehicle_id, user_id)
);

-- Subtype table: Cars
CREATE TABLE IF NOT EXISTS vehicle_car (
    vehicle_id         INT8 PRIMARY KEY,
    length_m           DECIMAL(4,2),
    width_m            DECIMAL(4,2),
    needs_ev_charging  INT2 DEFAULT 0 CHECK (needs_ev_charging IN (0, 1)),
    CONSTRAINT fk_car_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id) ON DELETE CASCADE
);

-- Subtype table: Two-wheelers / Motorcycles / Scooters
CREATE TABLE IF NOT EXISTS vehicle_bike (
    vehicle_id         INT8 PRIMARY KEY,
    engine_cc          INT4,
    is_electric        INT2 DEFAULT 0 CHECK (is_electric IN (0, 1)),
    CONSTRAINT fk_bike_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id) ON DELETE CASCADE
);

-- Subtype table: Trucks / Commercial vehicles
CREATE TABLE IF NOT EXISTS vehicle_truck (
    vehicle_id         INT8 PRIMARY KEY,
    max_weight_tons    DECIMAL(6,2),
    height_m           DECIMAL(4,2),
    axle_count         INT2,
    CONSTRAINT fk_truck_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id) ON DELETE CASCADE
);

-- Subtype table: Dedicated Electric Vehicles
CREATE TABLE IF NOT EXISTS vehicle_ev (
    vehicle_id           INT8 PRIMARY KEY,
    battery_capacity_kwh DECIMAL(5,1),
    connector_type       STRING(30),
    charging_speed_kw    DECIMAL(5,1),
    CONSTRAINT fk_ev_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id) ON DELETE CASCADE
);
