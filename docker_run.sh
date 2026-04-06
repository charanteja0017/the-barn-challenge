#!/bin/bash
# docker_run.sh - Run the BARN Navigation Challenge in Docker
# Usage:
#   ./docker_run.sh python3 run.py --world_idx 0           # normal run
#   ./docker_run.sh --record 0                              # record 3D video of world 0
#   ./docker_run.sh --record 0 my_video.mp4                 # record with custom filename
#   ./docker_run.sh --trajectory 0                           # save trajectory for 2D animation
#
# If no arguments are given, defaults to running world 0.

set -e

IMAGE_NAME="barn-challenge:latest"

# Build the image if it doesn't exist
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo ">>> Building Docker image (this may take 10-20 minutes the first time)..."
    docker build -t "$IMAGE_NAME" .
    echo ">>> Build complete!"
fi

# Parse mode
MODE="normal"
if [ "$1" = "--record" ]; then
    MODE="record"
    WORLD_IDX="${2:-0}"
    OUTPUT_FILE="${3:-simulation_world_${WORLD_IDX}.mp4}"
    shift; shift 2>/dev/null || true; shift 2>/dev/null || true
elif [ "$1" = "--trajectory" ]; then
    MODE="trajectory"
    WORLD_IDX="${2:-0}"
    shift; shift 2>/dev/null || true
fi

if [ "$MODE" = "record" ]; then
    echo ">>> Recording simulation video for world ${WORLD_IDX} → ${OUTPUT_FILE}"
    docker run --rm \
        -v "$(pwd)":/jackal_ws/src/the-barn-challenge \
        --shm-size=512m \
        "$IMAGE_NAME" \
        bash record_sim.sh "$WORLD_IDX" "$OUTPUT_FILE"

elif [ "$MODE" = "trajectory" ]; then
    echo ">>> Running world ${WORLD_IDX} with trajectory saving"
    docker run --rm \
        -v "$(pwd)":/jackal_ws/src/the-barn-challenge \
        --shm-size=512m \
        "$IMAGE_NAME" \
        python3 run.py --world_idx "$WORLD_IDX" --save_trajectory
    
    echo ">>> Trajectory saved. Generate video with:"
    echo "    python3 visualize_trajectory.py --trajectory trajectory_world_${WORLD_IDX}.npy --world_idx ${WORLD_IDX}"

else
    # Default command if none provided
    if [ $# -eq 0 ]; then
        CMD="python3 run.py --world_idx 0"
    else
        CMD="$@"
    fi

    echo ">>> Running: $CMD"
    docker run --rm \
        -v "$(pwd)":/jackal_ws/src/the-barn-challenge \
        --shm-size=512m \
        "$IMAGE_NAME" \
        $CMD
fi
