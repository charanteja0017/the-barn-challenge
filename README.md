<p align="center">
  <img width="100%" src='res/BARN_Challenge.png' alt="BARN Challenge" />
</p>

--------------------------------------------------------------------------------

# ICRA 2026 BARN Challenge — Team 14
### Behaviour Cloning for Autonomous Robot Navigation in Dense Obstacle Environments

**Team 14 | IIT Kharagpur**
- Pampana Charan Teja (Leader) — 25AI60R22
- Pucha Arun Kumar — 25AI60R26
- Arkoti Charan Teja — 25AI60R19
- Bommireddi Nagendra — 25AI60R14
- Adarsh Raj — 25AI560R25

## 1. Project Overview & Objective

The goal of this project is to navigate a Clearpath Jackal robot (using 2D LiDAR) from a start coordinate to a goal across 360 highly constrained, unseen **BARN environments** (300 Static + 60 Dynamic). The objective is to achieve the highest possible **success rate** and navigation speed without collision.

**Hardware Constraint:** The simulation and physical deployment require the navigation stack to run on an **Intel i3 CPU without a GPU**, mandating highly optimized, real-time control (< 10ms inference per step).

### Key Methodologies (Our Approach):
1. **Behavior Cloning (BC) Model:** A lightweight 1D Convolutional Neural Network (~300K parameters) imitating an expert classical planner (KUL+FM), taking 720 LiDAR rays and relative goal coordinates as input to predict linear and angular velocities.
2. **Three-Tier Safety Layer:** Overrides network predictions when obstacles fall within a 60° forward cone. Features soft-braking below `0.45m` and an emergency rigid halt/avoidance rotation below `0.25m`.
3. **Stuck Recovery FSM:** Safely breaks the robot loose from pathological geometry pockets if velocity drops below `0.05 m/s` for 2+ seconds by executing an automated rollback and turn sequence.

## 2. Directory Structure

We have heavily structured the repository for maximum clarity:

```text
the-barn-challenge/
├── Dockerfile                  # Self-contained ROS Docker configuration
├── docker_run.sh               # Universal wrapper to trigger everything
├── README.md                   # This documentation
│
├── nav_node.py                 # Core Navigation stack (BC + Safety Layer)
├── bc_model.py                 # Neural Network Architecture
├── run.py                      # Main Gazebo Simulation Executor
├── gazebo_simulation.py        # Gazebo-Python interface wrapper
│
├── models/                     # Weights & Checkpoints
│   ├── bc_model_best.pt        # PyTorch best weights
│   └── bc_model.onnx           # CPU-optimized ONNX graph
│
├── utils/                      # Auxiliary & Visualization Tools
│   ├── create_ppt.py           # Slide generator for PPT presentation
│   ├── generate_plots.py       # Matplotlib report plotting
│   ├── fix_camera_angle.py     # Forces Gazebo camera to natively track car
│   └── visualize_trajectory.py # Renders 2D top-down path maps
│
├── scripts/                    # Batch & Execution Scripts
│   ├── record_sim.sh           # Headless Xvfb → FFmpeg 3D Video Recorder
│   ├── run_batch.sh            # Runs 50-world evaluation batches
│   └── test.sh                 # Standard loop tester
│
└── presentation/               # Auto-generated reports and videos
    └── BARN_Challenge_Presentation.pptx
```

## 3. Installation & Setup

We strictly utilize **Docker** to ensure our ROS Melodic and Gazebo dependencies compile instantly and reproducibly on any system (macOS/Linux). 

1. Ensure the Docker daemon is running on your host machine.
2. The provided `docker_run.sh` entrypoint will automatically build the `barn-challenge:latest` image upon its first run (this takes ~10 minutes).

## 4. How to Use & Run

All interactions with the repository are done effortlessly through the `docker_run.sh` script to avoid host machine environment conflicts.

### Standard Simulation (Headless Metric Output)
To simply execute the robot in World 0 and view terminal times/collisions:
```bash
./docker_run.sh python3 run.py --world_idx 0
```

### Save Trajectory & Generate 2D Plots
To log the coordinate path and generate a 2D overhead navigation map of the run:
```bash
./docker_run.sh --trajectory 0
```
This drops the `.npy` path arrays into `outputs/trajectories/` and outputs the exact command to run the visualizer.

### Record 3D Simulation Video 🎥
We've engineered a headless pipeline using `Xvfb` and `ffmpeg` that renders the beautiful, fully-tracked 3D Jackal Gazebo window perfectly into an MP4 file on your host machine:

```bash
./docker_run.sh --record 0 presentation/gazebo_video_tracked.mp4
```
*The `fix_camera_angle.py` utility has embedded `<track_visual>` properties seamlessly into all worlds so the camera will dynamically follow the robot throughout the maze!*

### Run Batch Evaluations
To execute the baseline tester across an array of worlds to generate statistical JSON and TXT aggregated grading:
```bash
./docker_run.sh bash scripts/run_batch.sh 0 10 20 30 40
```

## 5. Visual Artifacts & Presentations

Run the provided PPT script to automatically generate the 15-page final report slide deck covering methodology, simulation results, and charts (embedded graphs generate automatically via `generate_plots.py`):
```bash
./docker_run.sh python3 utils/create_ppt.py
```
This is saved natively to the `presentation/` folder.

---
*Based on the original dataset provided by the [BARN Challenge Official Committee](https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html).*
