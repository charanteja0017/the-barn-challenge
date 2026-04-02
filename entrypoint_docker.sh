#!/bin/bash
set -e

# Source ROS workspace
source /jackal_ws/devel/setup.bash

# Navigate to the BARN challenge directory
cd /jackal_ws/src/the-barn-challenge

# Execute the provided command
exec "$@"
