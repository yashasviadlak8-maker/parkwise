import os
import time
import uuid
import random
import psycopg

DSN = os.getenv(
    "CRDB_URL",
    "postgresql://root@localhost:26257/parkwise?sslmode=disable",
)
SECONDS = int(os.getenv("SECONDS", "60"))
DELAY = float(os.getenv("DELAY", "0.05"))

VEHICLE_TYPES = ("CAR", "BIKE", "TRUCK", "EV")
inserted_users = 0
inserted_vehicles = 0
failed = 0
deadline = time.monotonic() + SECONDS

with psycopg.connect(DSN) as conn:
    while time.monotonic() < deadline:
        token = uuid.uuid4().hex
        vehicle_type = random.choice(VEHICLE_TYPES)

        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_master
                            (phone, email, password_hash, user_type)
                        VALUES (%s, %s, %s, 'REGISTERED')
                        RETURNING user_id
                        """,
                        (
                            f"+1{token[:10]}",
                            f"d6_{token}@example.test",
                            "d6_demo_hash",
                        ),
                    )
                    user_id = cur.fetchone()[0]

                    cur.execute(
                        """
                        INSERT INTO registered_user
                            (user_id, kyc_status, wallet_balance,
                             default_payment_method)
                        VALUES (%s, 'PENDING', 0.00, 'UPI')
                        """,
                        (user_id,),
                    )

                    cur.execute(
                        """
                        INSERT INTO vehicle
                            (user_id, license_plate, is_verified,
                             vehicle_type)
                        VALUES (%s, %s, 0, %s)
                        RETURNING vehicle_id
                        """,
                        (
                            user_id,
                            f"D6-{token[:12].upper()}",
                            vehicle_type,
                        ),
                    )
                    vehicle_id = cur.fetchone()[0]

                    if vehicle_type == "CAR":
                        cur.execute(
                            """
                            INSERT INTO vehicle_car
                                (vehicle_id, length_m, width_m,
                                 needs_ev_charging)
                            VALUES (%s, 4.20, 1.80, 0)
                            """,
                            (vehicle_id,),
                        )
                    elif vehicle_type == "BIKE":
                        cur.execute(
                            """
                            INSERT INTO vehicle_bike
                                (vehicle_id, engine_cc, is_electric)
                            VALUES (%s, 150, 0)
                            """,
                            (vehicle_id,),
                        )
                    elif vehicle_type == "TRUCK":
                        cur.execute(
                            """
                            INSERT INTO vehicle_truck
                                (vehicle_id, max_weight_tons, height_m,
                                 axle_count)
                            VALUES (%s, 5.00, 3.00, 2)
                            """,
                            (vehicle_id,),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO vehicle_ev
                                (vehicle_id, battery_capacity_kwh,
                                 connector_type, charging_speed_kw)
                            VALUES (%s, 60.0, 'TYPE2', 11.0)
                            """,
                            (vehicle_id,),
                        )

            inserted_users += 1
            inserted_vehicles += 1

            if inserted_users % 10 == 0:
                print(
                    f"Inserted users={inserted_users}, "
                    f"vehicles={inserted_vehicles}, failed={failed}",
                    flush=True,
                )

        except Exception as exc:
            failed += 1
            print(
                f"INSERT_FAILED count={failed} error={exc!r}",
                flush=True,
            )

        time.sleep(DELAY)

print(
    f"LOAD_COMPLETE users={inserted_users} "
    f"vehicles={inserted_vehicles} failed={failed}",
    flush=True,
)
if failed:
    raise SystemExit(1)
