# ParkWise — Smart Parking & Reservation System

Streamlit front end for the ParkWise Smart Parking & Reservation System (DBMS DA3).
Shows insert, update and delete against the database, plus the stored procedures and functions.
Streamlit front end and multi-engine database backend for the **ParkWise Smart Parking & Reservation System** (**DBMS DA2 & DA3**).

The application supports three execution modes controlled via environment variables in `core/db.py`:
1. **Built-in Mock Mode (SQLite)**: Default fallback when neither `ORA_DSN` nor `CRDB_URL` is set — runs out of the box on any laptop.
2. **DA2 — Oracle Database (`sql/`)**: Traditional relational backend using Oracle SQL, constraints, triggers, and PL/SQL stored procedures/functions.
3. **DA3 — CockroachDB Distributed SQL (`cockroach/`)**: Cloud-native 5-node distributed SQL backend with `SERIALIZABLE` isolation, Raft replication across 5 zones (`north`, `south`, `east`, `west`, `central`), SQL UDFs, and high-concurrency / node-failure survival demos.

---

## Quick Start (UI)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

With no database environment variables set, the app runs on built-in sample data so every page works immediately.

---

## DA2: Connect to Oracle Database (`sql/`)

1. Run the master setup script in SQL*Plus to create the schema, sequences, seed data, views, triggers, and PL/SQL procedures:
   ```sql
   -- In SQL*Plus connected as your Oracle user:
   @sql/run_setup.sql
   ```
2. Copy `.env.example` to `.env` and fill in your Oracle credentials:
   ```bash
   cp .env.example .env        # set ORA_USER, ORA_PASSWORD, ORA_DSN
   ```
   *(The application automatically detects and loads `.env` across Windows, macOS, and Linux).*
3. Start the application:
   ```bash
   streamlit run app.py
   ```

When `ORA_DSN` is set (and `CRDB_URL` is unset), every page connects live to Oracle.

### Oracle Stored Procedures & Functions (`sql/03_plsql_blocks.sql`)

| UI Action | Oracle Object |
|---|---|
| New booking | `BookParkingSlot(p_user_id, p_vehicle_id, p_slot_id, p_start, p_end, p_method, OUT p_booking_id, OUT p_total)` |
| Vehicle exit | `ProcessVehicleExit(p_booking_id, p_exit_time)` |
| Register vehicle | `sp_register_vehicle(p_user_id, p_plate, p_type, p_attr1, p_attr2, p_attr3, OUT p_vehicle_id)` |
| Find a slot | `FindAvailableSlots(p_zone, p_vehicle_type, p_start, p_end) RETURN SYS_REFCURSOR` |

---

## DA3: Connect to CockroachDB (`cockroach/`)

### 1. Start a Local 5-Node CockroachDB Cluster

Start 5 local nodes representing the 5 city zones (`north`, `south`, `east`, `west`, `central`) on SQL ports `26257..26261` (HTTP Console on `8080..8084`):

```bash
cockroach start --insecure --store=node1 --listen-addr=localhost:26257 --http-addr=localhost:8080 --locality=zone=north --join=localhost:26257,localhost:26258,localhost:26259,localhost:26260,localhost:26261 --background
cockroach start --insecure --store=node2 --listen-addr=localhost:26258 --http-addr=localhost:8081 --locality=zone=south --join=localhost:26257,localhost:26258,localhost:26259,localhost:26260,localhost:26261 --background
cockroach start --insecure --store=node3 --listen-addr=localhost:26259 --http-addr=localhost:8082 --locality=zone=east --join=localhost:26257,localhost:26258,localhost:26259,localhost:26260,localhost:26261 --background
cockroach start --insecure --store=node4 --listen-addr=localhost:26260 --http-addr=localhost:8083 --locality=zone=west --join=localhost:26257,localhost:26258,localhost:26259,localhost:26260,localhost:26261 --background
cockroach start --insecure --store=node5 --listen-addr=localhost:26261 --http-addr=localhost:8084 --locality=zone=central --join=localhost:26257,localhost:26258,localhost:26259,localhost:26260,localhost:26261 --background

cockroach init --insecure --host=localhost:26257
cockroach sql --insecure --host=localhost:26257 -e "CREATE DATABASE IF NOT EXISTS parkwise;"
```

Create the empty `parkwise` repository on github.com first. `.env` is git-ignored, so passwords are never pushed.


## DA3 Package C — Users, Vehicles, Scale and Justification

CockroachDB setup and cluster scripts are under `cockroach/c_users_vehicles/`. Start the five-node cluster with `bash cockroach/c_users_vehicles/scripts/cluster_up.sh` and check it with `bash cockroach/c_users_vehicles/scripts/cluster_status.sh`.

Set the application connection string with:

```bash
export CRDB_URL='postgresql://root@localhost:26257/parkwise?sslmode=disable'
```

Generate and load seed data using `python3 cockroach/c_users_vehicles/data/generate_c.py` and `python3 cockroach/c_users_vehicles/data/load_c.py`. Run the validation suite with `cockroach sql --insecure --host=localhost:26257 --database=parkwise < cockroach/c_users_vehicles/tests/validate_c.sql`. The latest run passed all 30 checks.

Start the UI with `streamlit run app.py`; the Package C page is `pages/3_Users_Vehicles.py`. D5 evidence is in `cockroach/c_users_vehicles/demos/d5_distsql_plan.txt`; D6 workload and evidence are in `cockroach/c_users_vehicles/demos/load_users.py` and `cockroach/c_users_vehicles/demos/d6_evidence.txt`. The saved D6 evidence does not prove workload and schema change ran simultaneously.

Stop the cluster with `bash cockroach/c_users_vehicles/scripts/cluster_down.sh`.
### 2. Load Schema, Logic & Bulk Data (Work Package B — Bookings, Payments, Logs & Disputes)

```bash
export CRDB_URL="postgresql://root@127.0.0.1:26257/parkwise?sslmode=disable"   # PowerShell: $env:CRDB_URL="postgresql://root@127.0.0.1:26257/parkwise?sslmode=disable"

cockroach sql --insecure --host=127.0.0.1:26257 -d parkwise -f cockroach/b_bookings/00_stubs_b.sql
cockroach sql --insecure --host=127.0.0.1:26257 -d parkwise -f cockroach/b_bookings/01_schema.sql
cockroach sql --insecure --host=127.0.0.1:26257 -d parkwise -f cockroach/b_bookings/03_logic.sql
python cockroach/b_bookings/data/generate_b.py
cockroach sql --insecure --host=127.0.0.1:26257 -d parkwise -f cockroach/b_bookings/99_fk_B.sql
```

### 3. Run Validation, Edge Cases & Distributed Demos

```bash
# Schema, row-count, overlap, and penalty UDF validation (11,324 rows across Module B)
cockroach sql --insecure --host=127.0.0.1:26257 -d parkwise -f cockroach/b_bookings/tests/validate_b.sql

# 10 negative & boundary edge-case tests (B1-B10)
python cockroach/b_bookings/tests/test_edge_cases_b.py

# Demo D3: 100-thread concurrent booking contention (same slot vs 100 distinct slots)
python cockroach/b_bookings/demos/concurrent_booking.py

# Demo D4: Raft node survival under failure (kills & restarts Node 3 zone=east during live workload)
python cockroach/b_bookings/demos/node_survival.py
```

### 4. Run the Streamlit UI on CockroachDB

Set `CRDB_URL` in your environment or `.env` file and launch Streamlit:

```bash
export CRDB_URL="postgresql://root@127.0.0.1:26257/parkwise?sslmode=disable"
streamlit run app.py
```

When `CRDB_URL` is set, `core/db.py` and `pages/2_Bookings.py` route operations through `core/crdb.py` and `core/booking_crdb.py` using `SERIALIZABLE` transactions, `SELECT ... FOR UPDATE` slot locking, and automatic `40001` (`SerializationFailure`) retry loops.

---

## Project Layout

```text
app.py                              Overview & live KPI dashboard
pages/
  1_Infrastructure.py               Zones, lots, slots, sensors & dynamic pricing
  2_Bookings.py                     Bookings, vehicle exits, penalties, payments & disputes (Oracle & CockroachDB)
  3_Users_and_Vehicles.py           Users, roles, vehicles & loyalty points
core/
  db.py                             Unified database router (Oracle / SQLite mock / CockroachDB switch)
  crdb.py                           CockroachDB psycopg v3 connection & 40001 retry helper
  booking_crdb.py                   CockroachDB SERIALIZABLE booking, exit, penalty & refund service layer
  ui.py                             Reusable table + insert/update/delete UI components
sql/                                DA2 Oracle SQL & PL/SQL scripts
  01_ddl_create_tables.sql          Oracle schema, constraints & sequences
  02_dml_sample_data.sql            Oracle sample data
  03_plsql_blocks.sql               Oracle stored procedures, functions & triggers
  04_views_and_queries.sql          Analytical views & complex SQL queries
  run_setup.sql                     One-command SQL*Plus setup script
cockroach/                          DA3 CockroachDB Distributed SQL modules
  b_bookings/                       Work Package B (Bookings, Consistency & Node Survival)
    00_stubs_b.sql                  Stand-in parent tables & contract IDs for standalone execution
    01_schema.sql                   penalty_tier, booking, payment, entry_exit_log, dispute
    03_logic.sql                    Progressive overstay SQL UDF fn_penalty(INT8)
    99_fk_B.sql                     Cross-module foreign keys for team merge
    data/generate_b.py              Fixed-seed (42) generator & COPY bulk loader (11,324 rows)
    tests/validate_b.sql            Verification queries
    tests/test_edge_cases_b.py      10 negative & boundary edge-case tests
    demos/concurrent_booking.py     Demo D3: 100-thread slot contention test
    demos/node_survival.py          Demo D4: Raft node kill & recovery test
```
