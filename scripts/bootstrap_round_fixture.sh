#!/usr/bin/env bash
# Convenience wrapper to record a round-level parity fixture inside the
# running docker compose stack.
#
# Usage:
#   scripts/bootstrap_round_fixture.sh <PROJECT_UUID> [output_filename]
#
# Default output: backend/tests/parity/fixtures/golden_round_001.json
#
# What happens:
#   1. Verifies the backend container is up.
#   2. Runs `python -m tests.parity.record_round` inside the backend container.
#   3. The output is written to a path inside the container that maps to the
#      local repo (because backend/ is volume-mounted in dev compose).
#   4. Reminds you to git add + commit the new fixture.
#
# Re-run any time to re-record after intentional behaviour changes (or use
# `pytest --update-golden` for in-place refresh during normal dev cycle).

set -euo pipefail

if [[ $# -lt 1 ]]; then
    cat <<USAGE >&2
Usage: $0 <PROJECT_UUID> [output_filename]

Examples:
  $0 ad9a3c12-2eb1-4a71-92c0-cb09b9d2f3a4
  $0 ad9a3c12-... golden_round_patent.json
USAGE
    exit 2
fi

PROJECT_ID="$1"
OUTPUT_NAME="${2:-golden_round_001.json}"
CONTAINER_OUTPUT="tests/parity/fixtures/${OUTPUT_NAME}"

if ! docker compose ps backend --status running 2>/dev/null | grep -q backend; then
    echo "❌ backend container is not running. Start it first:" >&2
    echo "   docker compose up -d backend worker" >&2
    exit 1
fi

echo "→ recording round for project=${PROJECT_ID:0:8} → ${OUTPUT_NAME}"
docker compose exec -T backend python -m tests.parity.record_round \
    --project-id "${PROJECT_ID}" \
    --output "${CONTAINER_OUTPUT}"

LOCAL_PATH="backend/${CONTAINER_OUTPUT}"
if [[ -f "${LOCAL_PATH}" ]]; then
    SIZE=$(wc -c < "${LOCAL_PATH}")
    echo "✓ wrote ${LOCAL_PATH} (${SIZE} bytes)"
    echo
    echo "Next steps:"
    echo "   git add ${LOCAL_PATH}"
    echo "   git commit -m 'test(parity): bootstrap round-level golden'"
    echo "   git push  # CI will start enforcing this fixture"
else
    echo "⚠ expected ${LOCAL_PATH} but didn't find it locally — check the volume mount." >&2
    exit 1
fi
