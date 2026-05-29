#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Stress Test Runner — Proxmox Linux VM
#
# Deploys stress tests to CT 250 (192.168.3.152) and runs them.
#
# Usage:
#   bash run_stress_on_vm.sh              # Run all stress tests
#   bash run_stress_on_vm.sh --property   # Property-based only
#   bash run_stress_on_vm.sh --stress     # Concurrency only
#   bash run_stress_on_vm.sh --chaos      # Chaos only
#   bash run_stress_on_vm.sh --endurance  # Endurance only
#   bash run_stress_on_vm.sh --linux      # Linux AT-SPI only
# ──────────────────────────────────────────────────────────────────────────

set -euo pipefail

VM="root@192.168.3.152"
REMOTE_DIR="/opt/desktop-agent"
LOCAL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Desktop-Agent Stress Test Runner — Proxmox Linux VM${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Step 1: Sync source code ────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Syncing source code to VM...${NC}"
rsync -az --delete \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='sessions' \
    --exclude='docs' \
    --exclude='.git' \
    "${LOCAL_DIR}/src/" "${VM}:${REMOTE_DIR}/src/"
rsync -az \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='test_linux_atspi_stress.py' \
    "${LOCAL_DIR}/tests/stress/" "${VM}:${REMOTE_DIR}/tests/stress/"
rsync -az \
    "${LOCAL_DIR}/tests/conftest.py" \
    "${LOCAL_DIR}/pyproject.toml" \
    "${VM}:${REMOTE_DIR}/"
echo -e "  ${GREEN}Done.${NC}"

# ── Step 2: Ensure dependencies ─────────────────────────────────────────
echo -e "${YELLOW}[2/5] Ensuring dependencies on VM...${NC}"
ssh "${VM}" "pip3 install --break-system-packages hypothesis pytest-timeout pytest-mock 2>&1 | tail -3"
echo -e "  ${GREEN}Done.${NC}"

# ── Step 3: Ensure environment ──────────────────────────────────────────
echo -e "${YELLOW}[3/5] Ensuring Xvfb + AT-SPI environment...${NC}"
ssh "${VM}" bash -s <<'REMOTE'
export DISPLAY=:99
# Ensure Xvfb is running
if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :99 -screen 0 1280x720x24 -ac &
    sleep 1
    echo "  Started Xvfb"
else
    echo "  Xvfb already running"
fi

# Ensure AT-SPI bus
export XDG_RUNTIME_DIR=/run/user/$(id -u)
if [ ! -S /run/user/$(id -u)/at-spi/bus ]; then
    /usr/libexec/at-spi-bus-launcher &
    sleep 1
    echo "  Started AT-SPI bus"
else
    echo "  AT-SPI bus already running"
fi

# Launch gnome-calculator for AT-SPI tests
if ! pgrep -x gnome-calculator > /dev/null; then
    DISPLAY=:99 nohup gnome-calculator > /dev/null 2>&1 &
    sleep 2
    echo "  Launched gnome-calculator"
else
    echo "  gnome-calculator already running"
fi
REMOTE
echo -e "  ${GREEN}Done.${NC}"

# ── Step 4: Run tests ───────────────────────────────────────────────────
echo -e "${YELLOW}[4/5] Running stress tests...${NC}"
echo ""

# Determine which tests to run based on CLI args
PYTEST_FLAGS=""
TEST_MARKER=""

case "${1:-all}" in
    --property)
        PYTEST_FLAGS="--run-property"
        TEST_MARKER="property"
        ;;
    --stress)
        PYTEST_FLAGS="--run-stress"
        TEST_MARKER="stress"
        ;;
    --chaos)
        PYTEST_FLAGS="--run-chaos"
        TEST_MARKER="chaos"
        ;;
    --endurance)
        PYTEST_FLAGS="--run-endurance"
        TEST_MARKER="endurance"
        ;;
    --linux)
        PYTEST_FLAGS="--run-stress"
        TEST_MARKER="linux AT-SPI"
        ;;
    *)
        PYTEST_FLAGS="--run-all-stress"
        TEST_MARKER="all"
        ;;
esac

echo -e "  Running: ${CYAN}${TEST_MARKER}${NC} tests"
echo ""

SSH_CMD="cd ${REMOTE_DIR} && \
export DISPLAY=:99 && \
export XDG_RUNTIME_DIR=/run/user/\$(id -u) && \
python3 -m pytest tests/stress/ \
    ${PYTEST_FLAGS} \
    -v \
    --timeout=120 \
    --tb=short \
    -p no:benchmark \
    --ignore=tests/stress/test_linux_atspi_stress.py \
    2>&1"

RESULT=0
ssh "${VM}" bash -c "\"${SSH_CMD}\"" || RESULT=$?

echo ""

# ── Step 5: Summary ─────────────────────────────────────────────────────
echo -e "${YELLOW}[5/5] Summary${NC}"
if [ $RESULT -eq 0 ]; then
    echo -e "  ${GREEN}ALL STRESS TESTS PASSED${NC}"
else
    echo -e "  ${RED}SOME TESTS FAILED (exit code: ${RESULT})${NC}"
fi
echo ""
echo -e "Stress test markers:"
echo -e "  ${CYAN}property${NC}  — Hypothesis property-based tests (input fuzzing, round-trips, invariants)"
echo -e "  ${CYAN}stress${NC}    — Concurrency stress (race conditions, deadlocks)"
echo -e "  ${CYAN}chaos${NC}     — Fault injection (disk, network, timeout, corruption)"
echo -e "  ${CYAN}endurance${NC} — Memory leaks, throughput, degradation"
echo ""

exit $RESULT
