#!/usr/bin/env bash
set -euo pipefail

# Note: PID-based shutdown is best-effort.
# Validating numeric PIDs and re-checking command-line arguments immediately
# before signaling significantly narrows the window for PID-reuse races on macOS,
# but cannot completely eliminate it without an OS-level process supervisor.
# This approach is intentionally proportionate for this student project.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "=== Stopping ParkWise CockroachDB Nodes ==="

FAILED=0

for i in {1..5}; do
    n=$i
    store_dir="data/node${n}"
    pid_file="data/node${n}.pid"

    if [[ ! -f "$pid_file" ]]; then
        echo "Node ${n}: No PID file found (${pid_file}). Process assumed stopped."
        continue
    fi

    pid=$(cat "$pid_file" 2>/dev/null || true)

    # 1. Validate numeric PID
    if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
        echo "WARNING Node ${n}: PID in ${pid_file} is non-numeric ('${pid}'). Preserving file, refusing to signal." >&2
        FAILED=1
        continue
    fi

    # 2. Check if process is alive
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "Node ${n}: Process ${pid} is not running. Stale PID file preserved."
        continue
    fi

    # 3. Best-effort process identity check immediately prior to signaling
    cmd_args=$(ps -p "$pid" -o args= 2>/dev/null || true)
    if [[ "$cmd_args" != *"cockroach"* ]] || [[ "$cmd_args" != *"$store_dir"* ]]; then
        echo "ERROR Node ${n}: PID ${pid} does not match expected store path ('${store_dir}') or binary ('cockroach')." >&2
        echo "  Command found: ${cmd_args}" >&2
        echo "  Refusing to signal unverified process. PID file preserved." >&2
        FAILED=1
        continue
    fi

    # 4. Immediate pre-signal liveness check to minimize PID-reuse race window
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "Node ${n}: Process ${pid} exited immediately before signal. Preserving PID file."
        continue
    fi

    echo "Node ${n}: Best-effort check passed for PID ${pid}. Sending SIGTERM..."
    kill -TERM "$pid"

    # 5. Bounded wait for process exit (up to 15s)
    STOPPED=0
    for attempt in {1..15}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            STOPPED=1
            break
        fi
        sleep 1
    done

    if [[ $STOPPED -eq 1 ]]; then
        echo "Node ${n}: Successfully terminated. Removing verified PID file."
        rm -f "$pid_file"
    else
        echo "ERROR Node ${n}: Process ${pid} did not exit within 15 seconds. PID file preserved." >&2
        FAILED=1
    fi
done

echo ""
echo "Note: Store data directories (data/node*) are preserved intact."

if [[ $FAILED -ne 0 ]]; then
    echo "=== Shutdown completed with errors/warnings. Check details above. ===" >&2
    exit 1
else
    echo "=== All nodes stopped cleanly. ==="
fi
