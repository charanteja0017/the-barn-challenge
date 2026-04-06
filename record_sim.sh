#!/bin/bash
# record_sim.sh - Run a BARN simulation and record the Gazebo window as video
# Usage: ./record_sim.sh [world_idx] [output_file]
#
# This script starts a virtual X display (Xvfb), launches Gazebo with GUI
# on that display, records the screen with ffmpeg, and saves the video.
#
# Requirements: xvfb, ffmpeg, mesa (installed in Dockerfile)

set -e

WORLD_IDX="${1:-0}"
OUTPUT_FILE="${2:-simulation_world_${WORLD_IDX}.mp4}"
RESOLUTION="1280x720"
FRAMERATE=15
DISPLAY_NUM=99

echo ">>> Starting virtual display :${DISPLAY_NUM} at ${RESOLUTION}"
Xvfb :${DISPLAY_NUM} -screen 0 ${RESOLUTION}x24 +extension GLX +render -noreset &
XVFB_PID=$!
sleep 2

export DISPLAY=:${DISPLAY_NUM}

# Force Gazebo UI to maximize and fill the 1280x720 frame
mkdir -p ~/.gazebo
cat <<EOF > ~/.gazebo/gui.ini
[geometry]
x=0
y=0
width=1280
height=720
EOF

cleanup() {
    echo ">>> Cleaning up recording and displays..."
    kill -SIGINT ${FFMPEG_PID} 2>/dev/null || true
    wait ${FFMPEG_PID} 2>/dev/null || true
    kill ${XVFB_PID} 2>/dev/null || true
    wait ${XVFB_PID} 2>/dev/null || true
}
trap cleanup EXIT SIGINT SIGTERM

echo ">>> Starting ffmpeg screen capture → ${OUTPUT_FILE}"
ffmpeg -f x11grab -video_size ${RESOLUTION} -framerate ${FRAMERATE} \
    -i :${DISPLAY_NUM} \
    -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
    -y "${OUTPUT_FILE}" &
FFMPEG_PID=$!
sleep 1

echo ">>> Launching simulation with world_idx=${WORLD_IDX} (GUI enabled)"
python3 run.py --world_idx ${WORLD_IDX} --gui
SIM_EXIT_CODE=$?

echo ">>> Simulation finished (exit code: ${SIM_EXIT_CODE}). Stopping recording..."

if [ -f "${OUTPUT_FILE}" ]; then
    echo ">>> Video saved: ${OUTPUT_FILE}"
    # Print video info
    ffprobe -v quiet -print_format json -show_format -show_streams "${OUTPUT_FILE}" 2>/dev/null | \
        python3 -c "
import sys, json
info = json.load(sys.stdin)
fmt = info.get('format', {})
dur = fmt.get('duration', '?')
size = int(fmt.get('size', 0))
print(f'    Duration: {dur}s, Size: {size/1024/1024:.1f} MB')
" 2>/dev/null || true
else
    echo ">>> WARNING: Video file was not created!"
fi

exit ${SIM_EXIT_CODE}
