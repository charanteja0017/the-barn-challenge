#!/bin/bash
# docker_run.sh - Run the BARN Navigation Challenge in Docker
# Usage: ./docker_run.sh python3 run.py --world_idx 0
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
