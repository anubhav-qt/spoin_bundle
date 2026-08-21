#!/usr/bin/env bash
# Linux launcher for Spoin CPU Idle Generation Runner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

export PYTHONPATH="${REPO_ROOT}/apps/api/src:${PYTHONPATH:-}"
export SPOIN_DATABASE_URL="${SPOIN_DATABASE_URL:-postgresql+asyncpg://spoin:spoin@localhost:5432/spoin_db}"

IDLE_MINUTES="${1:-15}"
CPU_THRESHOLD="${2:-15.0}"
LIMIT="${3:-1}"

echo "Starting Spoin CPU Idle Generation Runner for Linux..."
echo "  - Idle Requirement : ${IDLE_MINUTES} minutes"
echo "  - CPU Threshold    : < ${CPU_THRESHOLD}%"
echo "  - Topics per pass  : ${LIMIT}"
echo "  - Database         : ${SPOIN_DATABASE_URL}"

exec python3 -u "${SCRIPT_DIR}/idle_generation_runner.py" \
  --idle-minutes "${IDLE_MINUTES}" \
  --cpu-threshold "${CPU_THRESHOLD}" \
  --limit "${LIMIT}"
