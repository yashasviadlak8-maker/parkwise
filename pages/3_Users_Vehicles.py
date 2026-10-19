
import streamlit as st
import psycopg
from core import theme
from core.users_crdb import (
    get_crdb_url,
    register_vehicle,
    topup_wallet,
    zone_monthly_revenue,
)

theme.header()
st.title("Users and Vehicles — CockroachDB")

def connect():
    return psycopg.connect(get_crdb_url())

def create_user(phone, email):
    phone = phone.strip()
    email = email.strip().lower()
    if len(phone) != 10 or not phone.isdigit():
        raise ValueError("Phone must contain exactly 10 digits.")
    if not email or "@" not in email:
        raise ValueError("Enter a valid email address.")

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_master
                    (phone, email, password_hash, user_type)
                VALUES (%s, %s, %s, 'REGISTERED')
                RETURNING user_id
                """,
                (phone, email, "demo-password-hash"),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO registered_user
                    (user_id, kyc_status, wallet_balance)
                VALUES (%s, 'PENDING', 0)
                """,
                (uid,),
            )
    return uid

def update_user_kyc(user_id, status):
    if status not in ("PENDING", "VERIFIED", "REJECTED"):
        raise ValueError("Invalid KYC status.")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE registered_user
                SET kyc_status = %s
                WHERE user_id = %s
                RETURNING user_id
                """,
                (status, int(user_id)),
            )
            if cur.fetchone() is None:
                raise ValueError("Registered user not found.")

def update_vehicle_verification(vehicle_id, verified):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vehicle
                SET is_verified = %s
                WHERE vehicle_id = %s
                RETURNING vehicle_id
                """,
                (bool(verified), int(vehicle_id)),
            )
            if cur.fetchone() is None:
                raise ValueError("Vehicle not found.")

def read_rows(sql, params=()):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d.name for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

users_tab, vehicles_tab, wallet_tab, revenue_tab = st.tabs(
    ["Users", "Vehicles", "Wallet", "Monthly revenue"]
)

with users_tab:
    st.subheader("Register a user")
    with st.form("crdb_new_user", clear_on_submit=True):
        phone = st.text_input("10-digit phone")
        email = st.text_input("Email")
        submitted = st.form_submit_button("Register user")
        if submitted:
            try:
                uid = create_user(phone, email)
                st.success(f"User {uid} registered successfully.")
            except Exception as exc:
                st.error(str(exc))

    st.subheader("Update user KYC")
    with st.form("crdb_update_kyc"):
        kyc_user_id = st.number_input(
            "Registered user ID for KYC update", min_value=1, step=1
        )
        kyc_status = st.selectbox(
            "New KYC status", ["PENDING", "VERIFIED", "REJECTED"]
        )
        kyc_submitted = st.form_submit_button("Update KYC")
        if kyc_submitted:
            try:
                update_user_kyc(kyc_user_id, kyc_status)
                st.success(
                    f"KYC status for user {int(kyc_user_id)} updated to {kyc_status}."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if st.button("Refresh users", key="refresh_users"):
        st.rerun()

    try:
        rows = read_rows(
            """
            SELECT u.user_id, u.phone, u.email, u.user_type,
                   r.kyc_status, r.wallet_balance
            FROM user_master u
            LEFT JOIN registered_user r ON r.user_id = u.user_id
            ORDER BY u.user_id
            LIMIT 500
            """
        )
        st.dataframe(rows, width="stretch", hide_index=True)
    except Exception as exc:
        st.error(f"Could not load users: {exc}")

with vehicles_tab:
    st.subheader("Register a vehicle")
    with st.form("crdb_new_vehicle", clear_on_submit=True):
        uid = st.number_input("Registered owner user ID", min_value=1, step=1)
        plate = st.text_input("Number plate (e.g. TN 22 AB 1234)")
        vtype = st.selectbox("Vehicle type", ["CAR", "BIKE", "TRUCK", "EV"])

        a1 = a2 = a3 = None
        if vtype == "CAR":
            a1 = st.number_input("Length (metres)", min_value=0.1, value=4.0)
            a2 = st.number_input("Width (metres)", min_value=0.1, value=1.8)
            a3 = int(st.checkbox("Needs EV charging"))
        elif vtype == "BIKE":
            a1 = st.number_input("Engine capacity (cc)", min_value=1, value=150)
            a2 = int(st.checkbox("Electric bike"))
        elif vtype == "TRUCK":
            a1 = st.number_input("Maximum weight (tonnes)", min_value=0.1, value=5.0)
            a2 = st.number_input("Height (metres)", min_value=0.1, value=3.0)
            a3 = st.number_input("Axle count", min_value=2, value=2, step=1)
        else:
            a1 = st.number_input("Battery capacity (kWh)", min_value=1.0, value=40.0)
            a2 = st.selectbox("Connector type", ["CCS2", "Type 2", "CHAdeMO"])
            a3 = st.number_input("Charging speed (kW)", min_value=1.0, value=7.0)

        submitted = st.form_submit_button("Register vehicle")
        if submitted:
            try:
                vid = register_vehicle(
                    int(uid), plate, vtype, a1, a2, a3
                )
                st.success(f"Vehicle {vid} registered with its {vtype} subtype.")
            except Exception as exc:
                st.error(str(exc))

    st.subheader("Update vehicle verification")
    with st.form("crdb_update_vehicle_verification"):
        verify_vehicle_id = st.text_input(
            "Vehicle ID to update", placeholder="Paste the full vehicle ID"
        )
        verified = st.selectbox(
            "Verification status", ["Verified", "Not verified"]
        )
        verify_submitted = st.form_submit_button("Update verification")
        if verify_submitted:
            try:
                update_vehicle_verification(
                    int(verify_vehicle_id.strip()), verified == "Verified"
                )
                st.success(
                    f"Vehicle {verify_vehicle_id.strip()} verification updated."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    try:
        rows = read_rows(
            """
            SELECT v.vehicle_id, v.user_id, v.license_plate,
                   v.vehicle_type, v.is_verified, v.registration_date
            FROM vehicle v
            ORDER BY v.vehicle_id DESC
            LIMIT 500
            """
        )
        st.dataframe(rows, width="stretch", hide_index=True)
    except Exception as exc:
        st.error(f"Could not load vehicles: {exc}")

with wallet_tab:
    st.subheader("Top up a registered user's wallet")
    st.caption("Wallet top-up requires VERIFIED KYC; amount must be above 0 and at most ₹10,000.")
    with st.form("crdb_wallet_topup"):
        uid = st.number_input("User ID", min_value=1, step=1, key="wallet_uid")
        amount = st.number_input(
            "Amount (₹)", min_value=1.0, max_value=10000.0, value=100.0
        )
        submitted = st.form_submit_button("Top up wallet")
        if submitted:
            try:
                balance = topup_wallet(int(uid), amount)
                st.success(f"Top-up successful. New wallet balance: ₹{balance:.2f}")
            except Exception as exc:
                st.error(str(exc))

with revenue_tab:
    st.subheader("Zone monthly net revenue")
    col1, col2, col3 = st.columns(3)
    with col1:
        zone = st.selectbox(
            "Zone", ["1 - NORTH", "2 - SOUTH", "3 - EAST", "4 - WEST", "5 - CENTRAL"]
        )
    with col2:
        month = st.selectbox("Month", list(range(1, 13)), index=9)
    with col3:
        year = st.number_input("Year", min_value=2000, max_value=2100, value=2026)

    if st.button("Calculate net revenue"):
        try:
            zone_id = int(zone.split(" - ")[0])
            amount = zone_monthly_revenue(zone_id, int(month), int(year))
            st.metric("Net revenue", f"₹{amount:,.2f}")
        except Exception as exc:
            st.error(str(exc))
