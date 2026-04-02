# BARN Navigation Challenge - Docker Setup
# Based on the Singularityfile.def, converted for Docker
FROM ros:melodic

# Avoid interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Create workspace
RUN mkdir -p /jackal_ws/src

# Install Python 3 venv and pip
RUN apt-get -y update && \
    apt-get -y install python3-venv python3-pip git && \
    rm -rf /var/lib/apt/lists/*

# Create virtual environment and install Python dependencies
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"
RUN pip3 install --upgrade pip && \
    pip3 install defusedxml rospkg netifaces numpy

# Clone required ROS packages
# Note: jackal_desktop omitted (rviz/GUI not needed for headless testing)
# hector_gazebo cloned from source since apt package unavailable for EOL Melodic
WORKDIR /jackal_ws/src
RUN git clone https://github.com/jackal/jackal.git --branch melodic-devel && \
    git clone https://github.com/jackal/jackal_simulator.git --branch melodic-devel && \
    git clone https://github.com/utexas-bwi/eband_local_planner.git && \
    git clone https://github.com/tu-darmstadt-ros-pkg/hector_gazebo.git

# Create stub pointgrey_camera_description package.
# The Jackal URDF unconditionally includes these xacro files even when cameras
# are disabled. This stub satisfies rospack's find requirement without adding
# camera hardware dependencies.
RUN mkdir -p /jackal_ws/src/pointgrey_camera_description/urdf && \
    echo '<?xml version="1.0"?><package format="2"><name>pointgrey_camera_description</name><version>0.0.0</version><description>Stub</description><maintainer email="stub@stub.com">stub</maintainer><license>BSD</license><buildtool_depend>catkin</buildtool_depend></package>' \
        > /jackal_ws/src/pointgrey_camera_description/package.xml && \
    printf '<?xml version="1.0"?>\n<robot xmlns:xacro="http://www.ros.org/wiki/xacro">\n  <xacro:macro name="pointgrey_flea3" params="frame name camera_x camera_y camera_z camera_mass hfov fps width height">\n    <link name="${frame}"/>\n  </xacro:macro>\n</robot>\n' \
        > /jackal_ws/src/pointgrey_camera_description/urdf/pointgrey_flea3.urdf.xacro && \
    printf '<?xml version="1.0"?>\n<robot xmlns:xacro="http://www.ros.org/wiki/xacro">\n  <xacro:macro name="BB2-08S2C-38" params="frame name">\n    <link name="${frame}"/>\n  </xacro:macro>\n</robot>\n' \
        > /jackal_ws/src/pointgrey_camera_description/urdf/pointgrey_bumblebee2.urdf.xacro && \
    printf 'cmake_minimum_required(VERSION 2.8.3)\nproject(pointgrey_camera_description)\nfind_package(catkin REQUIRED)\ncatkin_package()\n' \
        > /jackal_ws/src/pointgrey_camera_description/CMakeLists.txt

# Copy the BARN challenge code into the workspace
COPY . /jackal_ws/src/the-barn-challenge

# Install ROS dependencies and build the workspace
# --include-eol-distros: include Melodic (EOL) in rosdep database
# --skip-keys: skip packages unavailable in apt for EOL Melodic
WORKDIR /jackal_ws
RUN /bin/bash -c "source /opt/ros/melodic/setup.bash && \
    apt-get update && \
    rosdep update --include-eol-distros && \
    rosdep install -y --from-paths src --ignore-src --rosdistro=melodic \
        --skip-keys 'pointgrey_camera_description' && \
    catkin_make"

# Set up the environment
ENV PATH="/venv/bin:$PATH"

# Entrypoint: source the workspace and run commands
COPY entrypoint_docker.sh /entrypoint_docker.sh
RUN chmod +x /entrypoint_docker.sh
ENTRYPOINT ["/entrypoint_docker.sh"]
CMD ["python3", "run.py", "--world_idx", "0"]
