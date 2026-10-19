import os
import streamlit as st
from datetime import datetime, timedelta
from core import db, theme
from core.ui import crud

IS_CRDB = bool(os.getenv("CRDB_URL"))
if IS_CRDB:
    from core import booking_crdb

theme.header()
st.title("Bookings")
view, new, status, pay, exit_, disp = st.tabs(
    ["All bookings", "New booking", "Change status", "Payments", "Vehicle exit", "Disputes"]
)

with view:
    st.dataframe(db.query("SELECT * FROM booking ORDER BY booking_id DESC LIMIT 200" if IS_CRDB else "SELECT * FROM booking ORDER BY booking_id"), width="stretch", hide_index=True)

with new:
    with st.form("book"):
        a, b, c = st.columns(3)
        uid = int(a.number_input("User id", step=1, value=1))
        vid = int(b.number_input("Vehicle id", step=1, value=1))
        sid = int(c.number_input("Slot id", step=1, value=1))
        d1, d2, d3 = st.columns(3)
        day = d1.date_input("Date", datetime.now())
        t1 = d2.time_input("From", datetime.now().replace(minute=0, second=0, microsecond=0).time())
        t2 = d3.time_input("To", (datetime.now() + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0).time())
        method = st.selectbox("Payment method", ["UPI", "CARD", "WALLET", "CASH"])
        if st.form_submit_button("Book slot"):
            try:
                start_dt, end_dt = datetime.combine(day, t1), datetime.combine(day, t2)
                if IS_CRDB:
                    bid, total = booking_crdb.book_slot(uid, vid, sid, start_dt, end_dt, method)
                else:
                    bid, total = db.book_slot(uid, vid, sid, start_dt, end_dt, method)
                st.success(f"Booking {bid} confirmed. Total ₹{total:.2f}")
            except Exception as e:
                st.error(str(e))

with status:
    if IS_CRDB:
        rows = db.query("SELECT * FROM booking ORDER BY booking_id DESC LIMIT 200")
        st.dataframe(rows, width="stretch", hide_index=True)
        if rows:
            rid = st.selectbox("booking_id", [r["booking_id"] for r in rows], key="booking_u_id")
            val = st.selectbox("New status", ["PENDING", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"], key="booking_u_val")
            if st.button("Save change", key="booking_u_btn"):
                try:
                    booking_crdb.update_booking_status(rid, val)
                    st.success(f"Booking {rid} status updated to {val} (slot occupancy synced).")
                except Exception as e:
                    st.error(str(e))
    else:
        crud("booking", "booking_id", {"status": ["PENDING", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"]}, allow=("update",))

with pay:
    if IS_CRDB:
        rows = db.query("SELECT * FROM payment ORDER BY payment_id DESC LIMIT 200")
        st.dataframe(rows, width="stretch", hide_index=True)
        if rows:
            pid = st.selectbox("payment_id", [r["payment_id"] for r in rows], key="payment_u_id")
            val = st.selectbox("New status", ["PENDING", "SUCCESS", "FAILED", "REFUNDED"], key="payment_u_val")
            if st.button("Save change", key="payment_u_btn"):
                try:
                    res = booking_crdb.refund_payment(pid, val)
                    if res["credited"]:
                        st.success(
                            f"Payment {pid} marked REFUNDED — ₹{res['amount']:.2f} credited to User #{res['user_id']} wallet "
                            f"(New wallet balance: ₹{res['new_wallet_balance']:.2f})"
                        )
                    else:
                        st.success(f"Payment {pid} status updated to {val}.")
                except Exception as e:
                    st.error(str(e))
    else:
        crud("payment", "payment_id", {"status": ["PENDING", "SUCCESS", "FAILED", "REFUNDED"]}, allow=("update",))

with exit_:
    if IS_CRDB:
        active_rows = db.query(
            "SELECT b.booking_id, b.user_id, b.slot_id, b.start_time, b.end_time, b.status, l.entry_time, l.exit_time "
            "FROM booking b LEFT JOIN entry_exit_log l ON l.booking_id = b.booking_id "
            "WHERE b.status = 'ACTIVE' ORDER BY b.booking_id LIMIT 50"
        )
        if active_rows:
            st.caption("Active bookings ready for exit:")
            st.dataframe(active_rows, width="stretch", hide_index=True)
        default_bid = int(active_rows[0]["booking_id"]) if active_rows else 1
        c1, c2, c3 = st.columns(3)
        bid = int(c1.number_input("Booking id", step=1, value=default_bid, key="exit_bid"))
        exit_day = c2.date_input("Exit date", datetime.now().date(), key="exit_day")
        when = c3.time_input("Exit time", datetime.now().replace(second=0, microsecond=0).time(), key="exit_time")
        if st.button("Record exit"):
            try:
                res = booking_crdb.process_exit(bid, datetime.combine(exit_day, when))
                st.success(
                    f"Exit recorded; booking #{bid} completed. "
                    f"Duration: {res['duration_min']} min | Overstay: {res['overstay_min']} min | "
                    f"Penalty: ₹{res['penalty']:.2f}"
                )
            except Exception as e:
                st.error(str(e))
    else:
        bid = int(st.number_input("Booking id", step=1, value=1, key="exit_bid"))
        when = st.time_input("Exit time", datetime.now().time())
        if st.button("Record exit"):
            try:
                db.process_exit(bid, datetime.combine(datetime.now().date(), when))
                st.success("Exit recorded; booking completed.")
            except Exception as e:
                st.error(str(e))

with disp:
    crud(
        "dispute",
        "dispute_id",
        {
            "booking_id": "int",
            "raised_by": "int",
            "status": ["OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"],
            "resolution_notes": "text",
        },
    )
