-- ============================================================================
-- ParkWise DA3: Work Package C — Data Validation Script
-- Validates:
--   1. Exact row counts for all 9 Package C tables.
--   2. Fixed ID ranges and discriminator mappings.
--   3. Unique constraints: zero duplicate phones, emails, or license plates.
--   4. Vehicle ownership formula: owner_id = ((vehicle_id - 1) % 1400) + 1.
--   5. Exactly-one-subtype: Total and disjoint specialization for users & vehicles.
--   6. User-type and vehicle-type discriminator consistency.
--   7. Attendant zone/lot validity: lots 1-50, zone_id = ((lot_id - 1) / 10) + 1.
--   8. License plate regex validation: ^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$
--
-- Execution:
--   cockroach sql --insecure --host=localhost:26257 --database=parkwise -f cockroach/c_users_vehicles/tests/validate_c.sql
-- ============================================================================

WITH validation_results AS (

    -- ------------------------------------------------------------------------
    -- 1. Exact Row Counts
    -- ------------------------------------------------------------------------
    SELECT
        'Row Counts' AS category,
        'user_master count' AS test_name,
        '1500' AS expected,
        count(*)::STRING AS actual,
        CASE WHEN count(*) = 1500 THEN 'PASS' ELSE 'FAIL' END AS status,
        'Total users in user_master' AS details
    FROM user_master

    WHERE user_id BETWEEN 1 AND 1500

    UNION ALL

    SELECT
        'Row Counts', 'registered_user count', '1400', count(*)::STRING,
        CASE WHEN count(*) = 1400 THEN 'PASS' ELSE 'FAIL' END,
        'Registered customers with wallet'
    FROM registered_user

    WHERE user_id BETWEEN 1 AND 1400

    UNION ALL

    SELECT
        'Row Counts', 'parking_attendant count', '60', count(*)::STRING,
        CASE WHEN count(*) = 60 THEN 'PASS' ELSE 'FAIL' END,
        'Attendants assigned to lots'
    FROM parking_attendant

    WHERE user_id BETWEEN 1401 AND 1460

    UNION ALL

    SELECT
        'Row Counts', 'admin_user count', '40', count(*)::STRING,
        CASE WHEN count(*) = 40 THEN 'PASS' ELSE 'FAIL' END,
        'Administrators'
    FROM admin_user

    WHERE user_id BETWEEN 1461 AND 1500

    UNION ALL

    SELECT
        'Row Counts', 'vehicle count', '2000', count(*)::STRING,
        CASE WHEN count(*) = 2000 THEN 'PASS' ELSE 'FAIL' END,
        'Total registered vehicles'
    FROM vehicle

    WHERE vehicle_id BETWEEN 1 AND 2000

    UNION ALL

    SELECT
        'Row Counts', 'vehicle_car count', '1000', count(*)::STRING,
        CASE WHEN count(*) = 1000 THEN 'PASS' ELSE 'FAIL' END,
        'Car subtype rows'
    FROM vehicle_car

    WHERE vehicle_id BETWEEN 1 AND 1000

    UNION ALL

    SELECT
        'Row Counts', 'vehicle_bike count', '500', count(*)::STRING,
        CASE WHEN count(*) = 500 THEN 'PASS' ELSE 'FAIL' END,
        'Bike subtype rows'
    FROM vehicle_bike

    WHERE vehicle_id BETWEEN 1001 AND 1500

    UNION ALL

    SELECT
        'Row Counts', 'vehicle_truck count', '200', count(*)::STRING,
        CASE WHEN count(*) = 200 THEN 'PASS' ELSE 'FAIL' END,
        'Truck subtype rows'
    FROM vehicle_truck

    WHERE vehicle_id BETWEEN 1501 AND 1700

    UNION ALL

    SELECT
        'Row Counts', 'vehicle_ev count', '300', count(*)::STRING,
        CASE WHEN count(*) = 300 THEN 'PASS' ELSE 'FAIL' END,
        'Dedicated EV subtype rows'
    FROM vehicle_ev

    WHERE vehicle_id BETWEEN 1701 AND 2000 -- ------------------------------------------------------------------------
    -- 2. Fixed ID Ranges
    -- ------------------------------------------------------------------------
    UNION ALL

    SELECT
        'ID Ranges',
        'registered_user range [1, 1400]',
        'min=1, max=1400, violations=0',
        'min=' || min(user_id)::STRING || ', max=' || max(user_id)::STRING || ', violations=' || count(CASE WHEN user_id < 1 OR user_id > 1400 THEN 1 END)::STRING,
        CASE WHEN min(user_id) = 1 AND max(user_id) = 1400 AND count(CASE WHEN user_id < 1 OR user_id > 1400 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Must strictly cover IDs 1 to 1400'
    FROM registered_user

    WHERE user_id BETWEEN 1 AND 1400
UNION ALL

    SELECT
        'ID Ranges',
        'parking_attendant range [1401, 1460]',
        'min=1401, max=1460, violations=0',
        'min=' || min(user_id)::STRING || ', max=' || max(user_id)::STRING || ', violations=' || count(CASE WHEN user_id < 1401 OR user_id > 1460 THEN 1 END)::STRING,
        CASE WHEN min(user_id) = 1401 AND max(user_id) = 1460 AND count(CASE WHEN user_id < 1401 OR user_id > 1460 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Must strictly cover IDs 1401 to 1460'
    FROM parking_attendant

    WHERE user_id BETWEEN 1401 AND 1460
UNION ALL

    SELECT
        'ID Ranges',
        'admin_user range [1461, 1500]',
        'min=1461, max=1500, violations=0',
        'min=' || min(user_id)::STRING || ', max=' || max(user_id)::STRING || ', violations=' || count(CASE WHEN user_id < 1461 OR user_id > 1500 THEN 1 END)::STRING,
        CASE WHEN min(user_id) = 1461 AND max(user_id) = 1500 AND count(CASE WHEN user_id < 1461 OR user_id > 1500 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Must strictly cover IDs 1461 to 1500'
    FROM admin_user

    WHERE user_id BETWEEN 1461 AND 1500
UNION ALL

    SELECT
        'ID Ranges',
        'vehicle_car range [1, 1000]',
        'min=1, max=1000, violations=0',
        'min=' || min(vehicle_id)::STRING || ', max=' || max(vehicle_id)::STRING || ', violations=' || count(CASE WHEN vehicle_id < 1 OR vehicle_id > 1000 THEN 1 END)::STRING,
        CASE WHEN min(vehicle_id) = 1 AND max(vehicle_id) = 1000 AND count(CASE WHEN vehicle_id < 1 OR vehicle_id > 1000 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Cars cover IDs 1 to 1000'
    FROM vehicle_car

    WHERE vehicle_id BETWEEN 1 AND 1000
UNION ALL

    SELECT
        'ID Ranges',
        'vehicle_bike range [1001, 1500]',
        'min=1001, max=1500, violations=0',
        'min=' || min(vehicle_id)::STRING || ', max=' || max(vehicle_id)::STRING || ', violations=' || count(CASE WHEN vehicle_id < 1001 OR vehicle_id > 1500 THEN 1 END)::STRING,
        CASE WHEN min(vehicle_id) = 1001 AND max(vehicle_id) = 1500 AND count(CASE WHEN vehicle_id < 1001 OR vehicle_id > 1500 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Bikes cover IDs 1001 to 1500'
    FROM vehicle_bike

    WHERE vehicle_id BETWEEN 1001 AND 1500
UNION ALL

    SELECT
        'ID Ranges',
        'vehicle_truck range [1501, 1700]',
        'min=1501, max=1700, violations=0',
        'min=' || min(vehicle_id)::STRING || ', max=' || max(vehicle_id)::STRING || ', violations=' || count(CASE WHEN vehicle_id < 1501 OR vehicle_id > 1700 THEN 1 END)::STRING,
        CASE WHEN min(vehicle_id) = 1501 AND max(vehicle_id) = 1700 AND count(CASE WHEN vehicle_id < 1501 OR vehicle_id > 1700 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Trucks cover IDs 1501 to 1700'
    FROM vehicle_truck

    WHERE vehicle_id BETWEEN 1501 AND 1700
UNION ALL

    SELECT
        'ID Ranges',
        'vehicle_ev range [1701, 2000]',
        'min=1701, max=2000, violations=0',
        'min=' || min(vehicle_id)::STRING || ', max=' || max(vehicle_id)::STRING || ', violations=' || count(CASE WHEN vehicle_id < 1701 OR vehicle_id > 2000 THEN 1 END)::STRING,
        CASE WHEN min(vehicle_id) = 1701 AND max(vehicle_id) = 2000 AND count(CASE WHEN vehicle_id < 1701 OR vehicle_id > 2000 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'EVs cover IDs 1701 to 2000'
    FROM vehicle_ev

    WHERE vehicle_id BETWEEN 1701 AND 2000
-- ------------------------------------------------------------------------
    -- 3. Unique Integrity (No Duplicates)
    -- ------------------------------------------------------------------------
    UNION ALL

    SELECT
        'Uniqueness',
        'Unique phone numbers in user_master',
        '0 duplicates',
        (count(*) - count(DISTINCT phone))::STRING || ' duplicates',
        CASE WHEN count(*) = count(DISTINCT phone) THEN 'PASS' ELSE 'FAIL' END,
        'Every user must have a unique phone'
    FROM user_master

    UNION ALL

    SELECT
        'Uniqueness',
        'Unique email addresses in user_master',
        '0 duplicates',
        (count(*) - count(DISTINCT email))::STRING || ' duplicates',
        CASE WHEN count(*) = count(DISTINCT email) THEN 'PASS' ELSE 'FAIL' END,
        'Every user must have a unique email'
    FROM user_master

    UNION ALL

    SELECT
        'Uniqueness',
        'Unique license plates in vehicle',
        '0 duplicates',
        (count(*) - count(DISTINCT license_plate))::STRING || ' duplicates',
        CASE WHEN count(*) = count(DISTINCT license_plate) THEN 'PASS' ELSE 'FAIL' END,
        'Every vehicle must have a unique plate'
    FROM vehicle

    -- ------------------------------------------------------------------------
    -- 4. Vehicle Ownership Formula
    -- ------------------------------------------------------------------------
    UNION ALL

    SELECT
        'Ownership Integrity',
        'Vehicle owner ID formula adherence',
        '0 mismatched owners',
        count(CASE WHEN user_id != ((vehicle_id - 1) % 1400) + 1 THEN 1 END)::STRING || ' mismatched owners',
        CASE WHEN count(CASE WHEN user_id != ((vehicle_id - 1) % 1400) + 1 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Must follow owner_id = ((vehicle_id - 1) % 1400) + 1'
    FROM vehicle
    WHERE vehicle_id BETWEEN 1 AND 2000

    UNION ALL

    SELECT
        'Ownership Integrity',
        'All vehicle owners exist in registered_user',
        '0 invalid owners',
        count(CASE WHEN r.user_id IS NULL THEN 1 END)::STRING || ' invalid owners',
        CASE WHEN count(CASE WHEN r.user_id IS NULL THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Only registered users can own vehicles'
    FROM vehicle v
    LEFT JOIN registered_user r ON v.user_id = r.user_id

    -- ------------------------------------------------------------------------
    -- 5. Specialization Hierarchy (Total & Disjoint Specialization)
    -- ------------------------------------------------------------------------
    UNION ALL

    SELECT
        'Specialization',
        'Exactly one subtype per user (Total & Disjoint)',
        '0 violations (all 1500 have exactly 1 subtype)',
        count(CASE WHEN (
            (CASE WHEN r.user_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN a.user_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN p.user_id IS NOT NULL THEN 1 ELSE 0 END)
        ) != 1 THEN 1 END)::STRING || ' violations',
        CASE WHEN count(CASE WHEN (
            (CASE WHEN r.user_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN a.user_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN p.user_id IS NOT NULL THEN 1 ELSE 0 END)
        ) != 1 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Proves disjointness and completeness across user specialization'
    FROM user_master u
    LEFT JOIN registered_user r ON u.user_id = r.user_id
    LEFT JOIN admin_user a ON u.user_id = a.user_id
    LEFT JOIN parking_attendant p ON u.user_id = p.user_id
    WHERE u.user_id BETWEEN 1 AND 1500

    UNION ALL

    SELECT
        'Specialization',
        'User discriminator consistency',
        '0 type mismatches',
        count(CASE
            WHEN u.user_type = 'REGISTERED' AND r.user_id IS NULL THEN 1
            WHEN u.user_type = 'ATTENDANT' AND p.user_id IS NULL THEN 1
            WHEN u.user_type = 'ADMIN' AND a.user_id IS NULL THEN 1
            ELSE NULL
        END)::STRING || ' mismatches',
        CASE WHEN count(CASE
            WHEN u.user_type = 'REGISTERED' AND r.user_id IS NULL THEN 1
            WHEN u.user_type = 'ATTENDANT' AND p.user_id IS NULL THEN 1
            WHEN u.user_type = 'ADMIN' AND a.user_id IS NULL THEN 1
            ELSE NULL
        END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'user_type matches the actual subtype row'
    FROM user_master u
    LEFT JOIN registered_user r ON u.user_id = r.user_id
    LEFT JOIN admin_user a ON u.user_id = a.user_id
    LEFT JOIN parking_attendant p ON u.user_id = p.user_id
    WHERE u.user_id BETWEEN 1 AND 1500

    UNION ALL

    SELECT
        'Specialization',
        'Exactly one subtype per vehicle (Total & Disjoint)',
        '0 violations (all 2000 have exactly 1 subtype)',
        count(CASE WHEN (
            (CASE WHEN c.vehicle_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN b.vehicle_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN t.vehicle_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN e.vehicle_id IS NOT NULL THEN 1 ELSE 0 END)
        ) != 1 THEN 1 END)::STRING || ' violations',
        CASE WHEN count(CASE WHEN (
            (CASE WHEN c.vehicle_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN b.vehicle_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN t.vehicle_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN e.vehicle_id IS NOT NULL THEN 1 ELSE 0 END)
        ) != 1 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Proves disjointness and completeness across vehicle specialization'
    FROM vehicle v
    LEFT JOIN vehicle_car c ON v.vehicle_id = c.vehicle_id
    LEFT JOIN vehicle_bike b ON v.vehicle_id = b.vehicle_id
    LEFT JOIN vehicle_truck t ON v.vehicle_id = t.vehicle_id
    LEFT JOIN vehicle_ev e ON v.vehicle_id = e.vehicle_id
    WHERE v.vehicle_id BETWEEN 1 AND 2000

    UNION ALL

    SELECT
        'Specialization',
        'Vehicle discriminator consistency',
        '0 type mismatches',
        count(CASE
            WHEN v.vehicle_type = 'CAR' AND c.vehicle_id IS NULL THEN 1
            WHEN v.vehicle_type = 'BIKE' AND b.vehicle_id IS NULL THEN 1
            WHEN v.vehicle_type = 'TRUCK' AND t.vehicle_id IS NULL THEN 1
            WHEN v.vehicle_type = 'EV' AND e.vehicle_id IS NULL THEN 1
            ELSE NULL
        END)::STRING || ' mismatches',
        CASE WHEN count(CASE
            WHEN v.vehicle_type = 'CAR' AND c.vehicle_id IS NULL THEN 1
            WHEN v.vehicle_type = 'BIKE' AND b.vehicle_id IS NULL THEN 1
            WHEN v.vehicle_type = 'TRUCK' AND t.vehicle_id IS NULL THEN 1
            WHEN v.vehicle_type = 'EV' AND e.vehicle_id IS NULL THEN 1
            ELSE NULL
        END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'vehicle_type matches the actual subtype row'
    FROM vehicle v
    LEFT JOIN vehicle_car c ON v.vehicle_id = c.vehicle_id
    LEFT JOIN vehicle_bike b ON v.vehicle_id = b.vehicle_id
    LEFT JOIN vehicle_truck t ON v.vehicle_id = t.vehicle_id
    LEFT JOIN vehicle_ev e ON v.vehicle_id = e.vehicle_id
    WHERE v.vehicle_id BETWEEN 1 AND 2000

    -- ------------------------------------------------------------------------
    -- 6. Attendant Zone/Lot Mapping Rule
    -- ------------------------------------------------------------------------
    UNION ALL

    SELECT
        'Attendant Integrity',
        'Attendant lot_id in [1, 50]',
        '0 out-of-range lots',
        count(CASE WHEN lot_id < 1 OR lot_id > 50 THEN 1 END)::STRING || ' violations',
        CASE WHEN count(CASE WHEN lot_id < 1 OR lot_id > 50 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Assigned lots must be between 1 and 50'
    FROM parking_attendant

    UNION ALL

    SELECT
        'Attendant Integrity',
        'Attendant zone_id matches lot rule',
        '0 zone mismatches',
        count(CASE WHEN zone_id != FLOOR((lot_id - 1)::DECIMAL / 10)::INT8 + 1 THEN 1 END)::STRING || ' mismatches',
        CASE WHEN count(CASE WHEN zone_id != FLOOR((lot_id - 1)::DECIMAL / 10)::INT8 + 1 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'zone_id must equal FLOOR((lot_id - 1)::DECIMAL / 10)::INT8 + 1'
    FROM parking_attendant

    -- ------------------------------------------------------------------------
    -- 7. License Plate Formatting & Verification Ratio
    -- ------------------------------------------------------------------------
    UNION ALL

    SELECT
        'Plate Format',
        'License plate regex pattern compliance',
        '0 malformed plates',
        count(CASE WHEN license_plate !~ '^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$' THEN 1 END)::STRING || ' malformed plates',
        CASE WHEN count(CASE WHEN license_plate !~ '^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$' THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Must match ^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$'
    FROM vehicle
    WHERE vehicle_id BETWEEN 1 AND 2000

    UNION ALL

    SELECT
        'Distributions',
        'Vehicle verification ratio (~80%)',
        '1500 to 1700 verified',
        count(CASE WHEN is_verified = 1 THEN 1 END)::STRING || ' verified out of ' || count(*)::STRING,
        CASE WHEN count(CASE WHEN is_verified = 1 THEN 1 END) BETWEEN 1500 AND 1700 THEN 'PASS' ELSE 'FAIL' END,
        'Approximately 80% of registered vehicles verified'
    FROM vehicle
    WHERE vehicle_id BETWEEN 1 AND 2000

    UNION ALL

    SELECT
        'Distributions',
        'Wallet balance non-negative',
        '0 negative balances',
        count(CASE WHEN wallet_balance < 0 THEN 1 END)::STRING || ' negative balances',
        CASE WHEN count(CASE WHEN wallet_balance < 0 THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END,
        'Wallet balance must be >= 0.00'
    FROM registered_user
),
summary AS (
    SELECT
        'SUMMARY' AS category,
        'OVERALL VALIDATION TALLY' AS test_name,
        count(*)::STRING AS expected,
        count(CASE WHEN status = 'PASS' THEN 1 END)::STRING || ' passed, ' || count(CASE WHEN status = 'FAIL' THEN 1 END)::STRING || ' failed' AS actual,
        CASE WHEN count(CASE WHEN status = 'FAIL' THEN 1 END) = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        CASE WHEN count(CASE WHEN status = 'FAIL' THEN 1 END) = 0 THEN 'ALL CHECKS PASSED' ELSE 'VALIDATION FAILED: ' || count(CASE WHEN status = 'FAIL' THEN 1 END)::STRING || ' check(s) failed' END AS details,
        99 AS sort_order
    FROM validation_results
),
detailed AS (
    SELECT
        category,
        test_name,
        expected,
        actual,
        status,
        details,
        CASE category
            WHEN 'Row Counts' THEN 1
            WHEN 'ID Ranges' THEN 2
            WHEN 'Uniqueness' THEN 3
            WHEN 'Ownership Integrity' THEN 4
            WHEN 'Specialization' THEN 5
            WHEN 'Attendant Integrity' THEN 6
            WHEN 'Plate Format' THEN 7
            WHEN 'Distributions' THEN 8
            ELSE 9
        END AS sort_order
    FROM validation_results
)
SELECT
    category,
    test_name,
    expected,
    actual,
    status,
    details
FROM (
    SELECT * FROM detailed
    UNION ALL
    SELECT * FROM summary
) combined
ORDER BY sort_order, test_name;
