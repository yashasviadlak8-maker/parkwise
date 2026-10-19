-- ============================================================================
-- ParkWise DA3 — Work Package B: Cross-Owner Foreign Keys (99_fk_B.sql)
-- Run after all tables (A, C, B) and datasets are loaded.
-- ============================================================================

ALTER TABLE booking DROP CONSTRAINT IF EXISTS fk_booking_user;
ALTER TABLE booking DROP CONSTRAINT IF EXISTS fk_booking_vehicle_owner;
ALTER TABLE booking DROP CONSTRAINT IF EXISTS fk_booking_zone_slot;
ALTER TABLE dispute DROP CONSTRAINT IF EXISTS fk_dispute_raised_by;

ALTER TABLE booking
    ADD CONSTRAINT fk_booking_user
    FOREIGN KEY (user_id) REFERENCES registered_user(user_id);

ALTER TABLE booking
    ADD CONSTRAINT fk_booking_vehicle_owner
    FOREIGN KEY (vehicle_id, user_id) REFERENCES vehicle(vehicle_id, user_id);

ALTER TABLE booking
    ADD CONSTRAINT fk_booking_zone_slot
    FOREIGN KEY (zone_id, slot_id) REFERENCES parking_slot(zone_id, slot_id);

ALTER TABLE dispute
    ADD CONSTRAINT fk_dispute_raised_by
    FOREIGN KEY (raised_by) REFERENCES registered_user(user_id);
