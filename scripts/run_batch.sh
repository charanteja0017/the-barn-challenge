#!/bin/bash
# run_batch.sh - Run multiple BARN worlds with full metrics + trajectory saving
# Usage: ./run_batch.sh [world_indices...]
#        ./run_batch.sh                    # defaults: worlds 0,1,2,3,4
#        ./run_batch.sh 0 5 10 50 100 200  # specific worlds
#
# All outputs go to ./outputs/:
#   outputs/metrics.txt          - per-world raw metrics
#   outputs/summary.json         - aggregated JSON summary
#   outputs/trajectory_world_X.npy - trajectory data per world
#   outputs/logs/world_X.log     - full console log per world

set -e

IMAGE_NAME="barn-challenge:latest"
OUTPUT_DIR="outputs"

# Default worlds to run (a spread of easy to hard)
if [ $# -eq 0 ]; then
    WORLDS=(0 1 2 3 4)
else
    WORLDS=("$@")
fi

echo "=============================================="
echo " BARN Challenge Batch Runner"
echo " Worlds: ${WORLDS[*]}"
echo " Output: ./${OUTPUT_DIR}/"
echo "=============================================="

# Create output directories
mkdir -p "${OUTPUT_DIR}/logs"
mkdir -p "${OUTPUT_DIR}/trajectories"

# Build/rebuild Docker image
echo ""
echo ">>> Checking Docker image..."
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo ">>> Building Docker image (this may take 10-20 minutes)..."
    docker build -t "$IMAGE_NAME" .
    echo ">>> Build complete!"
else
    echo ">>> Image '$IMAGE_NAME' found. To rebuild: docker build -t $IMAGE_NAME ."
fi

# Clear previous metrics file
METRICS_FILE="${OUTPUT_DIR}/metrics.txt"
> "$METRICS_FILE"

TOTAL=${#WORLDS[@]}
SUCCESS_COUNT=0
COLLISION_COUNT=0
TIMEOUT_COUNT=0
START_BATCH=$(date +%s)

echo ""
echo ">>> Starting batch run of ${TOTAL} worlds..."
echo ""

for i in "${!WORLDS[@]}"; do
    WIDX=${WORLDS[$i]}
    NUM=$((i + 1))
    LOG_FILE="${OUTPUT_DIR}/logs/world_${WIDX}.log"
    TRAJ_FILE="outputs/trajectories/trajectory_world_${WIDX}.npy"

    echo "─────────────────────────────────────────────"
    echo "[${NUM}/${TOTAL}] World ${WIDX}"
    echo "─────────────────────────────────────────────"

    START_WORLD=$(date +%s)

    # Run simulation with trajectory saving, output to both console and log
    docker run --rm \
        -v "$(pwd)":/jackal_ws/src/the-barn-challenge \
        --shm-size=512m \
        "$IMAGE_NAME" \
        python3 run.py \
            --world_idx "$WIDX" \
            --out "outputs/metrics.txt" \
            --save_trajectory \
            --trajectory_file "$TRAJ_FILE" \
        2>&1 | tee "$LOG_FILE"

    END_WORLD=$(date +%s)
    ELAPSED=$((END_WORLD - START_WORLD))
    echo "  Wall time: ${ELAPSED}s"
    echo ""
done

END_BATCH=$(date +%s)
TOTAL_TIME=$((END_BATCH - START_BATCH))

echo ""
echo "=============================================="
echo " Batch Complete!"
echo " Total wall time: ${TOTAL_TIME}s"
echo " Raw metrics: ${METRICS_FILE}"
echo "=============================================="

# Print metrics table
echo ""
echo ">>> Results:"
echo "────────────────────────────────────────────────────────────────"
printf "%-8s %-10s %-10s %-10s %-12s %-10s\n" "World" "Success" "Collided" "Timeout" "Time(s)" "NavMetric"
echo "────────────────────────────────────────────────────────────────"

if [ -f "$METRICS_FILE" ]; then
    while read -r widx success collided timeout nav_time metric; do
        STATUS="FAIL"
        [ "$success" = "1" ] && STATUS="YES" && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        [ "$collided" = "1" ] && COLLISION_COUNT=$((COLLISION_COUNT + 1))
        [ "$timeout" = "1" ] && TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1))

        COLL_STR="no"
        [ "$collided" = "1" ] && COLL_STR="YES"
        TO_STR="no"
        [ "$timeout" = "1" ] && TO_STR="YES"

        printf "%-8s %-10s %-10s %-10s %-12s %-10s\n" "$widx" "$STATUS" "$COLL_STR" "$TO_STR" "$nav_time" "$metric"
    done < "$METRICS_FILE"
fi

echo "────────────────────────────────────────────────────────────────"
echo "Success: ${SUCCESS_COUNT}/${TOTAL}  |  Collisions: ${COLLISION_COUNT}  |  Timeouts: ${TIMEOUT_COUNT}"
echo ""

# Generate JSON summary
python3 -c "
import json, os, sys
metrics_file = '${METRICS_FILE}'
results = []
if os.path.exists(metrics_file):
    with open(metrics_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                results.append({
                    'world_idx': int(parts[0]),
                    'success': bool(int(parts[1])),
                    'collided': bool(int(parts[2])),
                    'timeout': bool(int(parts[3])),
                    'nav_time_s': float(parts[4]),
                    'nav_metric': float(parts[5])
                })

total = len(results)
successes = sum(1 for r in results if r['success'])
collisions = sum(1 for r in results if r['collided'])
timeouts = sum(1 for r in results if r['timeout'])
metrics = [r['nav_metric'] for r in results]
times = [r['nav_time_s'] for r in results if r['success']]

summary = {
    'total_worlds': total,
    'success_count': successes,
    'success_rate': round(successes / total, 4) if total > 0 else 0,
    'collision_count': collisions,
    'timeout_count': timeouts,
    'avg_nav_metric': round(sum(metrics) / len(metrics), 4) if metrics else 0,
    'avg_success_time_s': round(sum(times) / len(times), 2) if times else 0,
    'min_nav_metric': round(min(metrics), 4) if metrics else 0,
    'max_nav_metric': round(max(metrics), 4) if metrics else 0,
    'per_world_results': results,
    'total_wall_time_s': ${TOTAL_TIME}
}

out_path = '${OUTPUT_DIR}/summary.json'
with open(out_path, 'w') as f:
    json.dump(summary, f, indent=2)
print(f'>>> Summary saved to {out_path}')
print(json.dumps({k:v for k,v in summary.items() if k != 'per_world_results'}, indent=2))
" 2>&1 || echo "WARNING: Could not generate JSON summary"

# List trajectory files
echo ""
echo ">>> Trajectory files:"
ls -lh "${OUTPUT_DIR}/trajectories/" 2>/dev/null || echo "  (none found)"
echo ""
echo ">>> To generate trajectory videos, run:"
echo "    pip3 install matplotlib"
echo "    python3 utils/visualize_trajectory.py --trajectory outputs/trajectories/trajectory_world_0.npy --world_idx 0 --output outputs/trajectory_world_0.mp4"
