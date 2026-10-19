"""Single data-access layer. Every page talks to the database ONLY through this file.

Mode is chosen by env vars:
  ORA_DSN set   -> Oracle (real backend)
  ORA_DSN unset -> MOCK mode (in-memory SQLite with sample data, for UI work)

SQL in pages uses named binds (:name) and plain SQL that runs on both.
"""
import os, sqlite3
from pathlib import Path

# Load .env if present
for env_path in [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]:
    if env_path.is_file():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

CRDB = bool(os.getenv("CRDB_URL"))
MOCK = not os.getenv("ORA_DSN") and not CRDB
_mock = None


def _oracle():
    import oracledb
    return oracledb.connect(user=os.environ["ORA_USER"], password=os.environ["ORA_PASSWORD"], dsn=os.environ["ORA_DSN"])


def _conn():
    global _mock
    if MOCK:
        if _mock is None:
            _mock = _make_mock()
        return _mock
    return _oracle()


def query(sql, p=None):
    if CRDB:
        from core.crdb import query as crdb_query
        return crdb_query(sql, p)
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute(sql, p or {})
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        if not MOCK:
            c.close()


def execute(sql, p=None):
    if CRDB:
        from core.crdb import execute as crdb_execute
        return crdb_execute(sql, p)
    c = _conn()
    try:
        c.cursor().execute(sql, p or {})
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        if not MOCK:
            c.close()


def next_id(table, pk):
    """Oracle sequence, CockroachDB compatibility helper, or mock MAX+1."""
    if CRDB:
        from core.crdb import next_id as crdb_next_id
        return crdb_next_id(table, pk)
    if MOCK:
        return query(f"SELECT COALESCE(MAX({pk}),0)+1 AS n FROM {table}")[0]["n"]
    return query(f"SELECT seq_{table}.NEXTVAL AS n FROM dual")[0]["n"]


# ---- stored procedure / function wrappers (the backend contract) ----

def book_slot(user_id, vehicle_id, slot_id, start, end, method):
    """Oracle: BookParkingSlot(p_user_id,p_vehicle_id,p_slot_id,p_start,p_end,p_method,OUT p_booking_id,OUT p_total)"""
    if MOCK:
        rate = query("SELECT hourly_rate AS r FROM parking_slot WHERE slot_id=:s", {"s": slot_id})[0]["r"]
        hrs = max(1, -(-int((end - start).total_seconds()) // 3600))
        clash = query("SELECT 1 AS x FROM booking WHERE slot_id=:s AND status NOT IN ('CANCELLED','COMPLETED') "
                      "AND start_time < :e AND end_time > :b", {"s": slot_id, "e": end.isoformat(), "b": start.isoformat()})
        if clash:
            raise Exception("ORA-20001: slot already booked for that time window")
        bid, total = next_id("booking", "booking_id"), rate * hrs
        execute("INSERT INTO booking(booking_id,user_id,vehicle_id,slot_id,start_time,end_time,status,total_amount) "
                "VALUES(:i,:u,:v,:s,:b,:e,'CONFIRMED',:t)",
                {"i": bid, "u": user_id, "v": vehicle_id, "s": slot_id, "b": start.isoformat(), "e": end.isoformat(), "t": total})
        execute("INSERT INTO payment(payment_id,booking_id,amount,payment_method,status) VALUES(:i,:b,:a,:m,'SUCCESS')",
                {"i": next_id("payment", "payment_id"), "b": bid, "a": total, "m": method})
        return bid, total
    c = _oracle()
    try:
        cur = c.cursor()
        bid, tot = cur.var(int), cur.var(float)
        cur.execute("BEGIN BookParkingSlot(:u,:v,:s,:b,:e,:m,:bid,:tot); END;",
                    {"u": user_id, "v": vehicle_id, "s": slot_id, "b": start, "e": end, "m": method, "bid": bid, "tot": tot})
        return bid.getvalue(), tot.getvalue()
    finally:
        c.close()


def process_exit(booking_id, exit_time):
    """Oracle: ProcessVehicleExit(p_booking_id, p_exit_time)"""
    if MOCK:
        execute("UPDATE booking SET status='COMPLETED' WHERE booking_id=:b", {"b": booking_id})
        return
    execute("BEGIN ProcessVehicleExit(:b,:t); END;", {"b": booking_id, "t": exit_time})


def register_vehicle(user_id, plate, vtype):
    """Oracle: sp_register_vehicle(p_user_id,p_plate,p_type,p_attr1,p_attr2,p_attr3,OUT p_vehicle_id)"""
    if MOCK:
        execute("INSERT INTO vehicle(vehicle_id,user_id,license_plate,vehicle_type,is_verified) VALUES(:i,:u,:p,:t,0)",
                {"i": next_id("vehicle", "vehicle_id"), "u": user_id, "p": plate.upper(), "t": vtype})
        return
    c = _oracle()
    try:
        cur = c.cursor()
        cur.execute("BEGIN sp_register_vehicle(:u,:p,:t,NULL,NULL,NULL,:vid); END;",
                    {"u": user_id, "p": plate, "t": vtype, "vid": cur.var(int)})
    finally:
        c.close()


def find_slots(zone, vtype, start, end):
    """Oracle: FindAvailableSlots(p_zone,p_vehicle_type,p_start,p_end) RETURN SYS_REFCURSOR"""
    if MOCK:
        return query("SELECT s.slot_id, l.lot_name, s.slot_number, s.slot_type, s.hourly_rate FROM parking_slot s "
                     "JOIN parking_lot l ON l.lot_id=s.lot_id JOIN zone_config z ON z.zone_id=l.zone_id "
                     "WHERE z.zone_name=:z AND l.is_active=1 AND NOT (:t<>'EV' AND s.slot_type='EV') "
                     "AND NOT EXISTS (SELECT 1 FROM booking b WHERE b.slot_id=s.slot_id AND b.status NOT IN ('CANCELLED','COMPLETED') "
                     "AND b.start_time < :e AND b.end_time > :b)",
                     {"z": zone, "t": vtype, "e": end.isoformat(), "b": start.isoformat()})
    import oracledb
    c = _oracle()
    try:
        cur = c.cursor()
        rc = cur.callfunc("FindAvailableSlots", oracledb.CURSOR, [zone, vtype, start, end])
        cols = [d[0].lower() for d in rc.description]
        return [dict(zip(cols, r)) for r in rc.fetchall()]
    finally:
        c.close()


def _make_mock():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.executescript("""
    CREATE TABLE zone_config(zone_id INT PRIMARY KEY, zone_name TEXT, region_code TEXT, peak_multiplier REAL, ev_discount REAL);
    CREATE TABLE parking_lot(lot_id INT PRIMARY KEY, zone_id INT, manager_id INT, lot_name TEXT, address TEXT, latitude REAL, longitude REAL, total_slots INT DEFAULT 0, is_active INT DEFAULT 1);
    CREATE TABLE parking_slot(slot_id INT PRIMARY KEY, lot_id INT, slot_number INT, slot_type TEXT, floor_level INT, hourly_rate REAL, is_occupied INT DEFAULT 0);
    CREATE TABLE user_master(user_id INT PRIMARY KEY, phone TEXT, email TEXT, password_hash TEXT, created_at TEXT, user_type TEXT);
    CREATE TABLE registered_user(user_id INT PRIMARY KEY, kyc_status TEXT, wallet_balance REAL DEFAULT 0, default_payment_method TEXT);
    CREATE TABLE vehicle(vehicle_id INT PRIMARY KEY, user_id INT, license_plate TEXT, registration_date TEXT, is_verified INT DEFAULT 0, vehicle_type TEXT);
    CREATE TABLE booking(booking_id INT PRIMARY KEY, user_id INT, vehicle_id INT, slot_id INT, start_time TEXT, end_time TEXT, status TEXT, total_amount REAL);
    CREATE TABLE payment(payment_id INT PRIMARY KEY, booking_id INT, amount REAL, payment_method TEXT, status TEXT, transaction_ref TEXT, payment_timestamp TEXT);
    CREATE TABLE dispute(dispute_id INT PRIMARY KEY, booking_id INT, raised_by INT, status TEXT, resolution_notes TEXT);
    INSERT INTO zone_config VALUES (1,'NORTH','N01',1.3,0.1),(2,'SOUTH','S01',1.2,0.1),(3,'CENTRAL','C01',1.5,0.1);
    INSERT INTO parking_lot VALUES (1,1,NULL,'Anna Nagar Plaza','Anna Nagar',13.08,80.21,4,1),(2,2,NULL,'Adyar Hub','Adyar',13.00,80.25,4,1),(3,3,NULL,'T Nagar Deck','T Nagar',13.04,80.23,4,0);
    INSERT INTO parking_slot VALUES (1,1,1,'STANDARD',0,40,0),(2,1,2,'COMPACT',0,30,0),(3,1,3,'LARGE',1,55,0),(4,1,4,'EV',1,80,0),
      (5,2,1,'STANDARD',0,35,0),(6,2,2,'COMPACT',0,28,0),(7,2,3,'LARGE',0,50,0),(8,2,4,'EV',0,75,0),
      (9,3,1,'STANDARD',0,45,0),(10,3,2,'COMPACT',0,35,0),(11,3,3,'LARGE',0,60,0),(12,3,4,'EV',0,85,0);
    INSERT INTO user_master VALUES (1,'9876500001','asha@mail.com','h','2026-08-01','REGISTERED'),(2,'9876500002','ravi@mail.com','h','2026-08-03','REGISTERED'),(3,'9876500003','meena@mail.com','h','2026-08-05','REGISTERED');
    INSERT INTO registered_user VALUES (1,'VERIFIED',500,'UPI'),(2,'PENDING',120,'CARD'),(3,'VERIFIED',0,'WALLET');
    INSERT INTO vehicle VALUES (1,1,'TN 22 AB 1234','2026-08-02',1,'CAR'),(2,2,'TN 10 CD 5678','2026-08-04',1,'BIKE'),(3,3,'TN 01 EF 9012','2026-08-06',1,'EV');
    INSERT INTO booking VALUES (1,1,1,1,'2026-10-12T09:00:00','2026-10-12T11:00:00','CONFIRMED',80),(2,2,2,6,'2026-10-12T10:00:00','2026-10-12T12:00:00','ACTIVE',56);
    INSERT INTO payment VALUES (1,1,80,'UPI','SUCCESS','TX1','2026-10-11'),(2,2,56,'CARD','SUCCESS','TX2','2026-10-11');
    INSERT INTO dispute VALUES (1,1,1,'OPEN','');
    """)
    c.commit()
    return c
