#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

is_windows() {
    case "${OSTYPE:-}" in
        msys*|cygwin*|win32*) return 0 ;;
    esac
    [[ "${OS:-}" == "Windows_NT" ]]
}

detect_python() {
    local candidates=()
    if is_windows; then
        candidates=(py python python3)
    else
        candidates=(python3 python py)
    fi

    local candidate
    for candidate in "${candidates[@]}"; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            printf '%s' "${candidate}"
            return 0
        fi
    done

    echo "No supported Python launcher found. Tried: ${candidates[*]}" >&2
    exit 1
}

PATH_SEP=":"
if is_windows; then
    PATH_SEP=";"
fi

build_pythonpath() {
    local result=""
    local package_dir
    for package_dir in "${REPO_ROOT}"/packages/*; do
        [[ -d "${package_dir}" ]] || continue
        if [[ -z "${result}" ]]; then
            result="${package_dir}"
        else
            result="${result}${PATH_SEP}${package_dir}"
        fi
    done
    printf '%s' "${result}"
}

PYTHON_CMD="$(detect_python)"
export PYTHONPATH="$(build_pythonpath)"
eval "$("${PYTHON_CMD}" -c 'from csc_platform.platform import _platform_cli; _platform_cli(["csc-platform", "env"])' | grep '^export ')"

WORK_DIR="${CSC_TMP}/s2s-test"
mkdir -p "${WORK_DIR}"

SERVER1_PORT=19525
SERVER2_PORT=29525
SERVER1_HOST=127.0.0.1
SERVER2_HOST=127.0.0.1

SERVER1_PID_FILE="${WORK_DIR}/server1.pid"
SERVER2_PID_FILE="${WORK_DIR}/server2.pid"
SERVER1_LOG="${WORK_DIR}/server1.log"
SERVER2_LOG="${WORK_DIR}/server2.log"

is_pid_alive() {
    local pid="$1"
    "${PYTHON_CMD}" - "$pid" <<'PY'
import os
import sys

pid = int(sys.argv[1])
try:
    os.kill(pid, 0)
except OSError:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

start_server() {
    local name="$1"
    local host="$2"
    local port="$3"
    local peer="$4"
    local pid_file="$5"
    local log_file="$6"

    if [[ -f "${pid_file}" ]]; then
        local existing_pid
        existing_pid="$(cat "${pid_file}")"
        if is_pid_alive "${existing_pid}"; then
            echo "${name} already running with pid ${existing_pid}"
            return 0
        fi
        rm -f "${pid_file}"
    fi

    : > "${log_file}"
    nohup env \
        PYTHONPATH="${PYTHONPATH}" \
        CSC_ROOT="${CSC_ROOT}" \
        CSC_ETC="${CSC_ETC}" \
        CSC_LOGS="${CSC_LOGS}" \
        CSC_TMP="${CSC_TMP}" \
        "${PYTHON_CMD}" -u -m csc_server.main \
        --host "${host}" \
        --port "${port}" \
        --peer "${peer}" \
        --debug \
        > "${log_file}" 2>&1 &

    local pid=$!
    sleep 0.5
    if is_pid_alive "${pid}"; then
        echo "${pid}" > "${pid_file}"
        echo "started ${name} pid=${pid} port=${port}"
        return 0
    fi

    echo "${name} failed to stay up on port ${port}" >&2
    if [[ -f "${log_file}" ]]; then
        tail -n 20 "${log_file}" >&2 || true
    fi
    return 1
}

status_server() {
    local name="$1"
    local port="$2"
    local pid_file="$3"

    if [[ ! -f "${pid_file}" ]]; then
        echo "${name}: stopped (no pid file) port=${port}"
        return 0
    fi

    local pid
    pid="$(cat "${pid_file}")"
    if is_pid_alive "${pid}"; then
        echo "${name}: running pid=${pid} port=${port}"
    else
        echo "${name}: dead pid=${pid} port=${port}"
    fi
}

stop_server() {
    local name="$1"
    local pid_file="$2"

    if [[ ! -f "${pid_file}" ]]; then
        echo "${name} already stopped"
        return 0
    fi

    local pid
    pid="$(cat "${pid_file}")"
    if ! is_pid_alive "${pid}"; then
        rm -f "${pid_file}"
        echo "${name} not running; removed stale pid ${pid}"
        return 0
    fi

    "${PYTHON_CMD}" - "${pid}" <<'PY'
import os
import signal
import sys

pid = int(sys.argv[1])
os.kill(pid, signal.SIGTERM)
PY

    local _i
    for _i in 1 2 3 4 5 6 7 8 9 10; do
        if ! is_pid_alive "${pid}"; then
            rm -f "${pid_file}"
            echo "${name} stopped pid=${pid}"
            return 0
        fi
        sleep 0.2
    done

    "${PYTHON_CMD}" - "${pid}" <<'PY'
import os
import signal
import sys

pid = int(sys.argv[1])
os.kill(pid, signal.SIGKILL)
PY

    rm -f "${pid_file}"
    echo "${name} killed pid=${pid}"
}

dump_logs() {
    echo "== server1 log =="
    if [[ -f "${SERVER1_LOG}" ]]; then
        tail -n 10 "${SERVER1_LOG}"
    else
        echo "(missing)"
    fi
    echo
    echo "== server2 log =="
    if [[ -f "${SERVER2_LOG}" ]]; then
        tail -n 10 "${SERVER2_LOG}"
    else
        echo "(missing)"
    fi
}

usage() {
    cat <<EOF
Usage: $(basename "$0") {start|status|dump|stop}
EOF
}

cmd="${1:-}"
case "${cmd}" in
    start)
        start_server "server1" "${SERVER1_HOST}" "${SERVER1_PORT}" "${SERVER2_HOST}:${SERVER2_PORT}" "${SERVER1_PID_FILE}" "${SERVER1_LOG}"
        start_server "server2" "${SERVER2_HOST}" "${SERVER2_PORT}" "${SERVER1_HOST}:${SERVER1_PORT}" "${SERVER2_PID_FILE}" "${SERVER2_LOG}"
        ;;
    status)
        status_server "server1" "${SERVER1_PORT}" "${SERVER1_PID_FILE}"
        status_server "server2" "${SERVER2_PORT}" "${SERVER2_PID_FILE}"
        ;;
    dump)
        dump_logs
        ;;
    stop)
        stop_server "server1" "${SERVER1_PID_FILE}"
        stop_server "server2" "${SERVER2_PID_FILE}"
        ;;
    *)
        usage
        exit 1
        ;;
esac
