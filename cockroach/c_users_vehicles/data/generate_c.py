#!/usr/bin/env python3
"""ParkWise DA3: Work Package C — Deterministic Data Generator

Generates seed datasets for all 9 Package C tables:
  1. user_master          (1,500 rows)
  2. registered_user      (1,400 rows, IDs 1-1400)
  3. admin_user           (40 rows, IDs 1461-1500)
  4. parking_attendant    (60 rows, IDs 1401-1460)
  5. vehicle              (2,000 rows)
  6. vehicle_car          (1,000 rows, IDs 1-1000)
  7. vehicle_bike         (500 rows, IDs 1001-1500)
  8. vehicle_truck        (200 rows, IDs 1501-1700)
  9. vehicle_ev           (300 rows, IDs 1701-2000)

Contract Rules Enforced:
  - Seed reproducibility: fixed random seed (default 42).
  - Explicit fixed IDs: surrogate keys are written explicitly, never relying on unique_rowid().
  - Vehicle ownership formula: owner_id = ((vehicle_id - 1) % 1400) + 1.
  - License plate format: ^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$
  - Exactly-one-subtype: total and disjoint specialization strictly mapped.
  - Attendant assignment: lots 1-50 in rotation, zone_id = ((lot_id - 1) // 10) + 1.
"""

from __future__ import annotations

import csv
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix seeds for 100% deterministic reproducibility
SEED = 42
random.seed(SEED)

try:
    from faker import Faker
    fake = Faker("en_IN")
    Faker.seed(SEED)
except ImportError:
    fake = None  # Handled gracefully via deterministic fallback below

BASE_DIR = Path(__file__).resolve().parent

# Fallback Indian first/last names if Faker is not installed
INDIAN_FIRST_NAMES = [
    "Aarav", "Aditi", "Aditya", "Akash", "Ananya", "Aniket", "Anjali", "Arjun",
    "Deepak", "Divya", "Gaurav", "Harish", "Ishaan", "Kavita", "Kiran", "Lakshmi",
    "Manish", "Meena", "Neha", "Nikhil", "Pooja", "Pranav", "Priya", "Rahul",
    "Ravi", "Rohan", "Sanjay", "Shreya", "Sneha", "Suresh", "Varun", "Vikram"
]
INDIAN_LAST_NAMES = [
    "Agarwal", "Bose", "Chatterjee", "Deshmukh", "Gupta", "Iyer", "Joshi", "Kapoor",
    "Kumar", "Malhotra", "Mehta", "Nair", "Patel", "Pillai", "Rao", "Reddy",
    "Sharma", "Singh", "Sundaram", "Verma"
]

STATES = ["TN", "KA", "MH", "DL", "TS", "KL", "AP", "GJ", "HR", "UP"]
DEPARTMENTS = ["Operations", "Security", "Finance", "IT", "Administration"]
ACCESS_LEVELS = ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
KYC_STATUSES = ["VERIFIED", "PENDING", "REJECTED"]
KYC_WEIGHTS = [0.75, 0.15, 0.10]
PAYMENT_METHODS = ["UPI", "CARD", "WALLET", "CASH"]
CONNECTOR_TYPES = ["CCS2", "Type 2", "CHAdeMO", "GB/T"]


def _random_name(idx: int) -> str:
    if fake:
        return fake.name()
    fn = INDIAN_FIRST_NAMES[(idx * 7) % len(INDIAN_FIRST_NAMES)]
    ln = INDIAN_LAST_NAMES[(idx * 13) % len(INDIAN_LAST_NAMES)]
    return f"{fn} {ln}"


def _generate_plate(idx: int) -> str:
    """Generate plate matching ^[A-Z]{2} [0-9]{2} [A-Z]{1,3} [0-9]{4}$ deterministically."""
    state = STATES[(idx // 200) % len(STATES)]
    rto = f"{(idx % 80) + 10:02d}"
    # Deterministic 2-letter series
    c1 = chr(ord("A") + ((idx // 26) % 26))
    c2 = chr(ord("A") + (idx % 26))
    num = f"{(idx * 37 + 1000) % 9000 + 1000:04d}"
    return f"{state} {rto} {c1}{c2} {num}"


def generate_all() -> dict[str, list[dict]]:
    """Generate all 9 datasets in memory."""
    datasets: dict[str, list[dict]] = {
        "user_master": [],
        "registered_user": [],
        "admin_user": [],
        "parking_attendant": [],
        "vehicle": [],
        "vehicle_car": [],
        "vehicle_bike": [],
        "vehicle_truck": [],
        "vehicle_ev": [],
    }

    ref_date = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------------------
    # 1. user_master & subtypes (1,500 total users)
    #    IDs 1-1400:    REGISTERED
    #    IDs 1401-1460: ATTENDANT (60)
    #    IDs 1461-1500: ADMIN (40)
    # -------------------------------------------------------------------------
    used_phones: set[str] = set()
    used_emails: set[str] = set()

    for uid in range(1, 1501):
        if uid <= 1400:
            utype = "REGISTERED"
        elif uid <= 1460:
            utype = "ATTENDANT"
        else:
            utype = "ADMIN"

        # Unique 10-digit phone starting with 98 / 97 / 99
        phone_suffix = f"{uid:07d}"
        prefix = "98" if uid <= 1000 else ("97" if uid <= 1400 else "99")
        phone = f"{prefix}1{phone_suffix}"
        assert phone not in used_phones, f"Duplicate phone: {phone}"
        used_phones.add(phone)

        # Unique email
        email = f"user{uid:04d}@parkwise.in"
        assert email not in used_emails, f"Duplicate email: {email}"
        used_emails.add(email)

        # Created within past 365 days
        days_offset = (uid * 17) % 365
        created_at = (ref_date - timedelta(days=days_offset, hours=uid % 24)).strftime("%Y-%m-%d %H:%M:%S%z")

        datasets["user_master"].append({
            "user_id": uid,
            "phone": phone,
            "email": email,
            "password_hash": f"hash_seed_{uid:04d}",
            "created_at": created_at,
            "user_type": utype,
        })

        # Subtype row matching discriminator (disjoint & total specialization)
        if utype == "REGISTERED":
            kyc = random.choices(KYC_STATUSES, weights=KYC_WEIGHTS)[0]
            # Wallet between 0.00 and 2000.00
            wallet = round(random.uniform(0.00, 2000.00), 2)
            method = PAYMENT_METHODS[(uid * 3) % len(PAYMENT_METHODS)]
            datasets["registered_user"].append({
                "user_id": uid,
                "kyc_status": kyc,
                "wallet_balance": f"{wallet:.2f}",
                "default_payment_method": method,
            })
        elif utype == "ATTENDANT":
            # 60 attendants mapped to lots 1-50 in rotation
            attendant_idx = uid - 1401
            lot_id = (attendant_idx % 50) + 1
            zone_id = ((lot_id - 1) // 10) + 1
            shifts = [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")]
            shift_start, shift_end = shifts[attendant_idx % len(shifts)]
            is_active = 1 if attendant_idx < 55 else 0  # ~92% active

            datasets["parking_attendant"].append({
                "user_id": uid,
                "zone_id": zone_id,
                "lot_id": lot_id,
                "shift_start": shift_start,
                "shift_end": shift_end,
                "is_active": is_active,
            })
        elif utype == "ADMIN":
            admin_idx = uid - 1461
            dept = DEPARTMENTS[admin_idx % len(DEPARTMENTS)]
            access = ACCESS_LEVELS[admin_idx % len(ACCESS_LEVELS)]
            login_days = (admin_idx * 5) % 30
            last_login = (ref_date - timedelta(days=login_days, minutes=admin_idx * 13)).strftime("%Y-%m-%d %H:%M:%S%z")

            datasets["admin_user"].append({
                "user_id": uid,
                "department": dept,
                "access_level": access,
                "last_login": last_login,
            })

    # -------------------------------------------------------------------------
    # 2. vehicle & subtypes (2,000 total vehicles)
    #    IDs 1-1000:    CAR (1,000)
    #    IDs 1001-1500: BIKE (500)
    #    IDs 1501-1700: TRUCK (200)
    #    IDs 1701-2000: EV (300)
    # -------------------------------------------------------------------------
    used_plates: set[str] = set()

    for vid in range(1, 2001):
        if vid <= 1000:
            vtype = "CAR"
        elif vid <= 1500:
            vtype = "BIKE"
        elif vid <= 1700:
            vtype = "TRUCK"
        else:
            vtype = "EV"

        # Owner formula: ((vid - 1) % 1400) + 1
        owner_id = ((vid - 1) % 1400) + 1
        assert 1 <= owner_id <= 1400, f"Invalid owner {owner_id}"

        # Unique license plate
        plate = _generate_plate(vid)
        assert plate not in used_plates, f"Duplicate plate: {plate}"
        used_plates.add(plate)

        # Reg date within past year (calendar date format YYYY-MM-DD)
        reg_days = (vid * 13) % 360
        reg_date = (ref_date - timedelta(days=reg_days)).strftime("%Y-%m-%d")

        # ~80% verified
        is_verified = 1 if (vid % 5 != 0) else 0

        datasets["vehicle"].append({
            "vehicle_id": vid,
            "user_id": owner_id,
            "license_plate": plate,
            "registration_date": reg_date,
            "is_verified": is_verified,
            "vehicle_type": vtype,
        })

        # Vehicle subtype row
        if vtype == "CAR":
            length = round(3.60 + ((vid * 7) % 140) / 100.0, 2)  # 3.60m to 5.00m
            width = round(1.60 + ((vid * 3) % 35) / 100.0, 2)    # 1.60m to 1.95m
            needs_charging = 1 if (vid % 10 == 0) else 0
            datasets["vehicle_car"].append({
                "vehicle_id": vid,
                "length_m": f"{length:.2f}",
                "width_m": f"{width:.2f}",
                "needs_ev_charging": needs_charging,
            })
        elif vtype == "BIKE":
            cc = 100 + ((vid * 25) % 400)  # 100cc to 500cc
            is_elec = 1 if (vid % 8 == 0) else 0
            datasets["vehicle_bike"].append({
                "vehicle_id": vid,
                "engine_cc": cc,
                "is_electric": is_elec,
            })
        elif vtype == "TRUCK":
            weight = round(7.50 + ((vid * 19) % 320) / 10.0, 2)  # 7.50t to 39.50t
            height = round(2.80 + ((vid * 11) % 14) / 10.0, 2)   # 2.80m to 4.20m
            axles = 2 + (vid % 5)                                # 2 to 6
            datasets["vehicle_truck"].append({
                "vehicle_id": vid,
                "max_weight_tons": f"{weight:.2f}",
                "height_m": f"{height:.2f}",
                "axle_count": axles,
            })
        elif vtype == "EV":
            kwh = round(35.0 + ((vid * 13) % 650) / 10.0, 1)     # 35.0 to 100.0 kWh
            conn = CONNECTOR_TYPES[vid % len(CONNECTOR_TYPES)]
            speed = round(22.0 + ((vid * 17) % 1280) / 10.0, 1)  # 22.0 to 150.0 kW
            datasets["vehicle_ev"].append({
                "vehicle_id": vid,
                "battery_capacity_kwh": f"{kwh:.1f}",
                "connector_type": conn,
                "charging_speed_kw": f"{speed:.1f}",
            })

    return datasets


def write_csvs(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all generated datasets to CSV files in output_dir."""
    target_dir = output_dir or BASE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    datasets = generate_all()
    created_paths = {}

    for table_name, rows in datasets.items():
        if not rows:
            continue
        csv_path = target_dir / f"{table_name}.csv"
        headers = list(rows[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        created_paths[table_name] = csv_path
        print(f"Generated {csv_path.name}: {len(rows):5d} rows")

    return created_paths


if __name__ == "__main__":
    print(f"Generating deterministic Package C seed data (Seed={SEED})...")
    paths = write_csvs()
    print("Data generation complete. All 9 CSVs created successfully.")
