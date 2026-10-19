-- ============================================================================
-- ParkWise DA3: Work Package C — Cross-Module Foreign Keys
--
-- Cross-owner Foreign Key Contract (Package C -> Package A):
--   Table: parking_attendant
--   Columns: (zone_id, lot_id)
--   Referenced Table: parking_lot(zone_id, lot_id) [Owned by Package A]
--   Action: ON DELETE SET NULL
--
-- Execution Order:
--   Run only after all base tables and initial seed data for Packages A, B,
--   and C have been created and loaded (or after 00_stubs.sql in solo testing).
-- ============================================================================

-- Safely recreate the foreign key constraint without modifying the table structure
ALTER TABLE parking_attendant DROP CONSTRAINT IF EXISTS fk_attendant_lot;

ALTER TABLE parking_attendant
    ADD CONSTRAINT fk_attendant_lot
    FOREIGN KEY (zone_id, lot_id)
    REFERENCES parking_lot(zone_id, lot_id)
    ON DELETE SET NULL;
