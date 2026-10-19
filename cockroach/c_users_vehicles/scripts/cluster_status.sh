#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

ZONES=("north" "south" "east" "west" "central")

echo "================================================================================"
echo "                    ParkWise CockroachDB Cluster Status                         "
echo "================================================================================"

RUNNING_VERIFIED=0
SQL_READY_COUNT=0

printf "%-7s %-8s %-25s %-10s %-10s %-12s\n" \
    "NODE" "ZONE" "PROCESS STATE" "SQL PORT" "HTTP PORT" "SQL QUERY"
echo "--------------------------------------------------------------------------------"

for i in {1..5}; do
    n=$i
    zone="${ZONES[$((n-1))]}"
    sql_port=$((26256 + n))
    http_port=$((8079 + n))
    store_dir="data/node${n}"
    pid_file="data/node${n}.pid"

    proc_state="STOPPED"
    if [[ -f "$pid_file" ]]; then
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ "$pid" =~ ^[0-9]+$ ]]; then
            if kill -0 "$pid" 2>/dev/null; then
                cmd_args=$(ps -p "$pid" -o args= 2>/dev/null || true)
                if [[ "$cmd_args" == *"cockroach"* ]] && [[ "$cmd_args" == *"$store_dir"* ]]; then
                    proc_state="RUNNING (${pid})"
                    RUNNING_VERIFIED=$((RUNNING_VERIFIED + 1))
                else
                    proc_state="UNVERIFIED (${pid})"
                fi
            else
                proc_state="STALE PID (${pid})"
            fi
        else
            proc_state="INVALID PID"
        fi
    fi

    # Port checks via macOS BSD netcat (-G 1 timeout)
    sql_port_state="CLOSED"
    if nc -z -G 1 127.0.0.1 "$sql_port" 2>/dev/null; then
        sql_port_state="OPEN"
    fi

    http_port_state="CLOSED"
    if nc -z -G 1 127.0.0.1 "$http_port" 2>/dev/null; then
        http_port_state="OPEN"
    fi

    # Direct node SQL query test
    sql_test="FAIL"
    if cockroach sql --insecure --host=localhost:"$sql_port" -e "SELECT 1;" >/dev/null 2>&1; then
        sql_test="OK"
        SQL_READY_COUNT=$((SQL_READY_COUNT + 1))
    fi

    printf "Node %-2d %-8s %-25s %-10s %-10s %-12s\n" \
        "$n" "$zone" "$proc_state" "${sql_port} (${sql_port_state})" "${http_port} (${http_port_state})" "$sql_test"
done

echo "--------------------------------------------------------------------------------"
echo "Verified running processes: ${RUNNING_VERIFIED}/5 | Nodes accepting SQL: ${SQL_READY_COUNT}/5"
echo ""

# Cluster Consensus & Database Check
echo "--- Cluster Consensus & Database Health ---"
if nc -z -G 1 127.0.0.1 26257 2>/dev/null && cockroach sql --insecure --host=localhost:26257 -e "SELECT 1;" >/dev/null 2>&1; then
    echo "SQL Endpoint (localhost:26257): ONLINE"
    echo ""
    echo "Cluster Membership:"
    cockroach node status --insecure --host=localhost:26257 2>&1 || echo "Failed to retrieve node status."
    echo ""
    echo "Database 'parkwise' Check:"
    db_output=""
    if db_output=$(cockroach sql --insecure --host=localhost:26257 -e "SHOW DATABASES;" 2>&1); then
        if grep -qw "parkwise" <<< "$db_output"; then
            echo "Database 'parkwise': EXISTS and ACCESSIBLE."
        else
            echo "WARNING: Database 'parkwise' DOES NOT exist in database list."
        fi
    else
        echo "ERROR: 'SHOW DATABASES' query execution failed: ${db_output}"
    fi
else
    echo "SQL Endpoint (localhost:26257): UNREACHABLE or NOT READY (Cluster may be stopped or uninitialized)."
fi

echo "================================================================================"
echo "DB Console: http://localhost:8080"
echo "CRDB_URL:   postgresql://root@localhost:26257/parkwise?sslmode=disable"
echo "================================================================================"
