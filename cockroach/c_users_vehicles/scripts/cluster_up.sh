#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

ZONES=("north" "south" "east" "west" "central")
JOIN_ADDRS="localhost:26257,localhost:26258,localhost:26259"

# Diagnostic reporter for node states (read-only, never kills processes)
report_diagnostics() {
    echo ""
    echo "=== Diagnostic Report on Node States ==="
    for i in {1..5}; do
        n=$i
        zone="${ZONES[$((n-1))]}"
        sql_port=$((26256 + n))
        http_port=$((8079 + n))
        store_dir="data/node${n}"
        pid_file="data/node${n}.pid"

        p_status="NO_PID_FILE"
        if [[ -f "$pid_file" ]]; then
            pid=$(cat "$pid_file" 2>/dev/null || true)
            if [[ "$pid" =~ ^[0-9]+$ ]]; then
                if kill -0 "$pid" 2>/dev/null; then
                    cmd_args=$(ps -p "$pid" -o args= 2>/dev/null || true)
                    if [[ "$cmd_args" == *"cockroach"* ]] && [[ "$cmd_args" == *"$store_dir"* ]]; then
                        p_status="RUNNING (PID ${pid})"
                    else
                        p_status="UNVERIFIED_PID (${pid})"
                    fi
                else
                    p_status="STALE_PID (${pid} dead)"
                fi
            else
                p_status="INVALID_PID_FILE"
            fi
        fi

        sql_state="CLOSED"
        if nc -z -G 1 127.0.0.1 "$sql_port" 2>/dev/null; then
            sql_state="OPEN"
        fi

        http_state="CLOSED"
        if nc -z -G 1 127.0.0.1 "$http_port" 2>/dev/null; then
            http_state="OPEN"
        fi

        sql_queryable="NO"
        if cockroach sql --insecure --host=localhost:"$sql_port" -e "SELECT 1;" >/dev/null 2>&1; then
            sql_queryable="YES"
        fi

        printf "Node %d [%-7s]: Process: %-25s | SQL %5d: %-6s | HTTP %5d: %-6s | SQL Ready: %s\n" \
            "$n" "$zone" "$p_status" "$sql_port" "$sql_state" "$http_port" "$http_state" "$sql_queryable"
    done
    echo "========================================"
}

# Safety trap to guarantee diagnostics run on any unhandled error
trap_handler() {
    local exit_code=$1
    local line_no=$2
    echo "ERROR: Command failed at line ${line_no} with exit code ${exit_code}." >&2
    report_diagnostics
    exit "$exit_code"
}
trap 'trap_handler $? $LINENO' ERR

echo "=== Starting ParkWise CockroachDB 5-Node Local Cluster ==="

# 1. Inspect existing state and launch each node safely
for i in {1..5}; do
    n=$i
    zone="${ZONES[$((n-1))]}"
    sql_port=$((26256 + n))
    http_port=$((8079 + n))
    store_dir="data/node${n}"
    pid_file="data/node${n}.pid"

    # Strict check on existing PID files
    if [[ -f "$pid_file" ]]; then
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
            echo "ERROR: Node ${n} PID file (${pid_file}) contains invalid non-numeric PID: '${pid}'." >&2
            echo "Preserving PID file and data store. Aborting startup." >&2
            report_diagnostics
            exit 1
        fi

        if ! kill -0 "$pid" 2>/dev/null; then
            echo "ERROR: Node ${n} PID file (${pid_file}) exists (PID: ${pid}) but process is not running (stale)." >&2
            echo "Preserving PID file and data store. Aborting startup." >&2
            report_diagnostics
            exit 1
        fi

        cmd_args=$(ps -p "$pid" -o args= 2>/dev/null || true)
        if [[ "$cmd_args" != *"cockroach"* ]] || [[ "$cmd_args" != *"$store_dir"* ]]; then
            echo "ERROR: Node ${n} PID file (${pid_file}) belongs to PID ${pid}, but command line does not match this node." >&2
            echo "Command found: ${cmd_args}" >&2
            echo "Preserving PID file and data store. Aborting startup." >&2
            report_diagnostics
            exit 1
        fi

        # Verify ports and live SQL endpoint before treating as already healthy
        if ! nc -z -G 1 127.0.0.1 "$sql_port" 2>/dev/null; then
            echo "ERROR: Node ${n} process ${pid} is running, but SQL port ${sql_port} is closed." >&2
            report_diagnostics
            exit 1
        fi
        if ! nc -z -G 1 127.0.0.1 "$http_port" 2>/dev/null; then
            echo "ERROR: Node ${n} process ${pid} is running, but HTTP port ${http_port} is closed." >&2
            report_diagnostics
            exit 1
        fi
        if ! cockroach sql --insecure --host=localhost:"$sql_port" -e "SELECT 1;" >/dev/null 2>&1; then
            echo "ERROR: Node ${n} process ${pid} is running and ports are open, but SQL queries fail." >&2
            report_diagnostics
            exit 1
        fi

        echo "Node ${n} [${zone}]: Verified running, listening, and SQL-ready (PID: ${pid})."
        continue
    fi

    # Check for port collisions when PID file is absent
    if nc -z -G 1 127.0.0.1 "$sql_port" 2>/dev/null; then
        echo "ERROR: Node ${n} SQL port ${sql_port} is already in use by an untracked process." >&2
        report_diagnostics
        exit 1
    fi
    if nc -z -G 1 127.0.0.1 "$http_port" 2>/dev/null; then
        echo "ERROR: Node ${n} HTTP port ${http_port} is already in use by an untracked process." >&2
        report_diagnostics
        exit 1
    fi

    mkdir -p "$store_dir"

    echo "Node ${n} [${zone}]: Launching on SQL port ${sql_port}, HTTP port ${http_port}..."
    if ! cockroach start \
        --insecure \
        --store="path=${store_dir}" \
        --listen-addr="localhost:${sql_port}" \
        --http-addr="localhost:${http_port}" \
        --join="${JOIN_ADDRS}" \
        --locality="zone=${zone}" \
        --cache=128MiB \
        --max-sql-memory=128MiB \
        --pid-file="${pid_file}" \
        --background; then
        echo "ERROR: Failed to start CockroachDB node ${n}." >&2
        report_diagnostics
        exit 1
    fi
done

# 2. Bounded check for Node 1 process & port listening (up to 15s)
echo "Waiting for Node 1 process and listen port..."
NODE1_UP=0
for attempt in {1..15}; do
    if [[ -f "data/node1.pid" ]]; then
        p=$(cat "data/node1.pid" 2>/dev/null || true)
        if [[ "$p" =~ ^[0-9]+$ ]] && kill -0 "$p" 2>/dev/null; then
            if nc -z -G 1 127.0.0.1 26257 2>/dev/null; then
                NODE1_UP=1
                break
            fi
        fi
    fi
    sleep 1
done

if [[ $NODE1_UP -eq 0 ]]; then
    echo "ERROR: Node 1 failed to become ready on port 26257 within 15 seconds." >&2
    report_diagnostics
    exit 1
fi

# 3. Initialization check & safe execution (in-memory capture, no disk temps)
echo "Checking cluster initialization state..."
if cockroach sql --insecure --host=localhost:26257 -e "SELECT 1;" >/dev/null 2>&1; then
    echo "Cluster is already initialized (SQL check passed)."
else
    echo "Cluster uninitialized. Executing cockroach init..."
    INIT_OUT=$(cockroach init --insecure --host=localhost:26257 2>&1 || true)

    # Confirm SQL query execution succeeds after init
    SQL_READY=0
    for attempt in {1..15}; do
        if cockroach sql --insecure --host=localhost:26257 -e "SELECT 1;" >/dev/null 2>&1; then
            SQL_READY=1
            break
        fi
        sleep 1
    done

    if [[ $SQL_READY -eq 0 ]]; then
        echo "ERROR: Cluster initialization failed or SQL endpoint timed out." >&2
        echo "cockroach init output: ${INIT_OUT}" >&2
        report_diagnostics
        exit 1
    fi
    echo "Cluster successfully initialized."
fi

# 4. Verify individual SQL readiness on each of the 5 nodes (up to 20s)
echo "Verifying SQL readiness on all 5 nodes..."
ALL_SQL_READY=0
for attempt in {1..20}; do
    ready_count=0
    for n in {1..5}; do
        port=$((26256 + n))
        if cockroach sql --insecure --host=localhost:"$port" -e "SELECT 1;" >/dev/null 2>&1; then
            ready_count=$((ready_count + 1))
        fi
    done
    if [[ $ready_count -eq 5 ]]; then
        ALL_SQL_READY=1
        break
    fi
    sleep 1
done

if [[ $ALL_SQL_READY -eq 0 ]]; then
    echo "ERROR: Not all 5 nodes are responding to SQL queries within 20 seconds." >&2
    report_diagnostics
    exit 1
fi

# 5. Verify live node count with strict CSV row validation (up to 30s)
echo "Verifying cluster consensus membership (5 live nodes expected)..."
CONSENSUS_READY=0
LAST_OUTCOME="UNKNOWN"
LAST_MEASURED_COUNT="NONE"

for attempt in {1..30}; do
    raw_status=$(cockroach node status --insecure --host=localhost:26257 --format=csv 2>&1) && cmd_rc=0 || cmd_rc=$?

    if [[ $cmd_rc -ne 0 ]]; then
        LAST_OUTCOME="CLI_COMMAND_FAILED (exit ${cmd_rc}: ${raw_status})"
        sleep 1
        continue
    fi

    if [[ -z "$raw_status" ]]; then
        LAST_OUTCOME="CLI_EMPTY_OUTPUT"
        sleep 1
        continue
    fi

    awk_rc=0
    parsed_count=$(awk -F',' '
        BEGIN {
            err_code = 0
            live_col = 0
            header_nf = 0
            count = 0
        }
        NR == 1 {
            header_nf = NF
            for (i = 1; i <= NF; i++) {
                col = $i
                gsub(/^[ \t\r\n"]+|[ \t\r\n"]+$/, "", col)
                if (col == "is_live") {
                    live_col = i
                    break
                }
            }
            if (!live_col) {
                err_code = 2
                exit 2
            }
            next
        }
        # Skip completely empty lines
        NF == 0 || (NF == 1 && $1 ~ /^[ \t\r\n]*$/) { next }
        {
            if (NF != header_nf) {
                err_code = 3
                exit 3
            }
            val = $live_col
            gsub(/^[ \t\r\n"]+|[ \t\r\n"]+$/, "", val)
            if (val == "true" || val == "t" || val == "1") {
                count++
            } else if (val == "false" || val == "f" || val == "0") {
                # node recognized but currently not live
            } else {
                err_code = 4
                exit 4
            }
        }
        END {
            # If an error occurred earlier, exit immediately with no output
            if (err_code != 0) {
                exit err_code
            }
            if (!live_col) {
                exit 2
            }
            print count + 0
        }
    ' <<< "$raw_status") || awk_rc=$?

    if [[ $awk_rc -eq 2 ]]; then
        LAST_OUTCOME="MALFORMED_HEADER_NO_IS_LIVE (header: $(head -n 1 <<< "$raw_status"))"
    elif [[ $awk_rc -eq 3 ]]; then
        LAST_OUTCOME="MALFORMED_ROW_FIELD_COUNT (data row field count mismatch with header)"
    elif [[ $awk_rc -eq 4 ]]; then
        LAST_OUTCOME="UNEXPECTED_IS_LIVE_VALUE (non-boolean token encountered in is_live column)"
    elif [[ $awk_rc -ne 0 ]]; then
        LAST_OUTCOME="PARSER_ERROR (awk exit code ${awk_rc})"
    elif [[ ! "$parsed_count" =~ ^[0-9]+$ ]]; then
        LAST_OUTCOME="INVALID_COUNT_OUTPUT ('${parsed_count}')"
    else
        LAST_MEASURED_COUNT="$parsed_count"
        if [[ $parsed_count -ge 5 ]]; then
            CONSENSUS_READY=1
            break
        else
            LAST_OUTCOME="INSUFFICIENT_NODES (${parsed_count}/5 live nodes)"
        fi
    fi
    sleep 1
done

if [[ $CONSENSUS_READY -eq 0 ]]; then
    echo "ERROR: Cluster consensus verification failed after 30 seconds." >&2
    echo "  Failure reason: ${LAST_OUTCOME}" >&2
    if [[ "$LAST_MEASURED_COUNT" != "NONE" ]]; then
        echo "  Last measured live count: ${LAST_MEASURED_COUNT}/5" >&2
    fi
    report_diagnostics
    exit 1
fi

# 6. Idempotently ensure the target database exists
echo "Ensuring 'parkwise' database exists..."
if ! cockroach sql --insecure --host=localhost:26257 -e "CREATE DATABASE IF NOT EXISTS parkwise;"; then
    echo "ERROR: Failed to create or verify 'parkwise' database." >&2
    report_diagnostics
    exit 1
fi

# Disable trap on clean exit
trap - ERR

echo "=== Startup Complete ==="
echo "All 5 nodes are live, SQL-ready, and verified in cluster consensus."
echo "Connection URL: CRDB_URL=postgresql://root@localhost:26257/parkwise?sslmode=disable"
echo "DB Console UI:  http://localhost:8080"
