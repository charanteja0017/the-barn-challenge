"""
Generate synthetic expert data for Behavior Cloning from BARN dataset.

For each of the 300 worlds:
  1. Load the 30x30 occupancy grid and optimal path
  2. Simulate the robot following the path at discrete poses
  3. Raycast 720-beam LiDAR from each pose on the grid
  4. Compute expert (v*, omega*) from consecutive waypoints
  5. Compute goal features (d_goal, theta_goal)

Output: expert_data.npz with arrays:
  - lidar: (N, 720)
  - goal_features: (N, 4)  [d_goal, theta_goal, v_current, omega_current]
  - commands: (N, 2)  [v*, omega*]
"""

import os
import numpy as np
from pathlib import Path

# Grid/world constants
GRID_SIZE = 30
CELL_RADIUS = 0.075  # Each cell is a cylinder with this radius
CELL_DIAMETER = CELL_RADIUS * 2  # 0.15m per cell

# Robot constants
MAX_V = 2.0  # m/s max linear velocity
MAX_OMEGA = 2.0  # rad/s max angular velocity
DT = 0.1  # timestep for trajectory discretization

# LiDAR constants
NUM_RAYS = 720
LIDAR_MAX_RANGE = 10.0
LIDAR_FOV = 2 * np.pi  # 360 degrees


def grid_to_world(row, col):
    """Convert grid (row, col) to Gazebo world coordinates (x, y)."""
    x = row * CELL_DIAMETER + (-CELL_RADIUS - GRID_SIZE * CELL_DIAMETER)
    y = col * CELL_DIAMETER + (CELL_RADIUS + 5)
    return x, y


def raycast_lidar(grid, robot_x, robot_y, robot_theta, num_rays=NUM_RAYS,
                  max_range=LIDAR_MAX_RANGE):
    """
    Cast rays from robot pose on the occupancy grid.
    Returns array of (num_rays,) distances.
    """
    angles = np.linspace(-np.pi, np.pi, num_rays, endpoint=False) + robot_theta
    ranges = np.full(num_rays, max_range, dtype=np.float32)

    # Precompute occupied cell centers in world coords
    occupied = np.argwhere(grid == 1)
    if len(occupied) == 0:
        return ranges

    cell_centers = np.array([grid_to_world(r, c) for r, c in occupied])
    cell_x = cell_centers[:, 0]
    cell_y = cell_centers[:, 1]

    # For each ray, find intersection with nearest occupied cell
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    for i in range(num_rays):
        dx = cell_x - robot_x
        dy = cell_y - robot_y

        # Project cell centers onto ray direction
        proj = dx * cos_a[i] + dy * sin_a[i]

        # Perpendicular distance from ray
        perp = np.abs(-dx * sin_a[i] + dy * cos_a[i])

        # Cells that the ray could hit (in front, within cell radius)
        mask = (proj > 0) & (perp < CELL_RADIUS * 1.5)

        if np.any(mask):
            ranges[i] = min(ranges[i], np.min(proj[mask]))

    return ranges


def interpolate_path(path_points, step_size=0.05):
    """
    Interpolate path waypoints to get dense poses along the path.
    Returns: positions (N, 2) and headings (N,)
    """
    # Convert grid coords to world coords
    world_points = np.array([grid_to_world(r, c) for r, c in path_points])

    # Interpolate between consecutive points
    dense_points = []
    for i in range(len(world_points) - 1):
        p1 = world_points[i]
        p2 = world_points[i + 1]
        dist = np.linalg.norm(p2 - p1)
        if dist < 1e-6:
            continue
        n_steps = max(int(dist / step_size), 1)
        for t in np.linspace(0, 1, n_steps, endpoint=False):
            dense_points.append(p1 + t * (p2 - p1))
    dense_points.append(world_points[-1])
    dense_points = np.array(dense_points)

    # Compute headings from consecutive positions
    headings = np.zeros(len(dense_points))
    for i in range(len(dense_points) - 1):
        dx = dense_points[i + 1, 0] - dense_points[i, 0]
        dy = dense_points[i + 1, 1] - dense_points[i, 1]
        headings[i] = np.arctan2(dy, dx)
    headings[-1] = headings[-2] if len(headings) > 1 else 0

    return dense_points, headings


def compute_expert_commands(positions, headings, dt=DT):
    """
    Compute expert (v, omega) from trajectory.
    v = distance / dt, omega = delta_heading / dt
    """
    N = len(positions)
    commands = np.zeros((N, 2), dtype=np.float32)

    for i in range(N - 1):
        dist = np.linalg.norm(positions[i + 1] - positions[i])
        v = np.clip(dist / dt, 0, MAX_V)

        dtheta = headings[i + 1] - headings[i]
        # Normalize angle to [-pi, pi]
        dtheta = (dtheta + np.pi) % (2 * np.pi) - np.pi
        omega = np.clip(dtheta / dt, -MAX_OMEGA, MAX_OMEGA)

        commands[i] = [v, omega]

    # Last command same as second-to-last
    if N > 1:
        commands[-1] = commands[-2]

    return commands


def compute_goal_features(positions, headings, goal_pos):
    """
    Compute (d_goal, theta_goal) for each timestep.
    theta_goal is relative angle to goal in robot frame.
    """
    N = len(positions)
    features = np.zeros((N, 2), dtype=np.float32)

    for i in range(N):
        dx = goal_pos[0] - positions[i, 0]
        dy = goal_pos[1] - positions[i, 1]
        d_goal = np.sqrt(dx ** 2 + dy ** 2)

        # Angle to goal in world frame
        angle_to_goal = np.arctan2(dy, dx)
        # Relative to robot heading
        theta_goal = angle_to_goal - headings[i]
        theta_goal = (theta_goal + np.pi) % (2 * np.pi) - np.pi

        features[i] = [d_goal, theta_goal]

    return features


def process_world(world_idx, dataset_dir, subsample_step=3):
    """
    Process a single world: generate LiDAR, goal features, expert commands.
    subsample_step: take every Nth point to reduce dataset size.
    """
    grid_path = os.path.join(dataset_dir, "grid_files", f"grid_{world_idx}.npy")
    path_path = os.path.join(dataset_dir, "path_files", f"path_{world_idx}.npy")
    cspace_path = os.path.join(dataset_dir, "cspace_files", f"cspace_{world_idx}.npy")

    grid = np.load(grid_path)
    path_points = np.load(path_path, allow_pickle=True)

    # Use C-space grid for raycasting (accounts for robot footprint)
    cspace = np.load(cspace_path)

    if len(path_points) < 2:
        return None

    # Interpolate path to get dense poses
    positions, headings = interpolate_path(path_points, step_size=0.03)

    if len(positions) < 2:
        return None

    # Goal is the last point on the path
    goal_pos = positions[-1]

    # Compute expert commands
    commands = compute_expert_commands(positions, headings)

    # Compute goal features
    goal_feats = compute_goal_features(positions, headings, goal_pos)

    # Subsample for efficiency
    indices = np.arange(0, len(positions), subsample_step)

    # Raycast LiDAR at each sampled pose
    lidar_data = []
    for idx in indices:
        lidar = raycast_lidar(grid, positions[idx, 0], positions[idx, 1],
                              headings[idx])
        lidar_data.append(lidar)

    lidar_data = np.array(lidar_data)
    goal_feats = goal_feats[indices]
    commands = commands[indices]

    # Build goal_features: [d_goal, theta_goal, v_current, omega_current]
    # v_current and omega_current from previous timestep (0 for first)
    v_current = np.zeros(len(indices), dtype=np.float32)
    omega_current = np.zeros(len(indices), dtype=np.float32)
    for i in range(1, len(indices)):
        v_current[i] = commands[i - 1, 0]
        omega_current[i] = commands[i - 1, 1]

    full_goal_features = np.column_stack([goal_feats, v_current, omega_current])

    return lidar_data, full_goal_features, commands


def main():
    dataset_dir = os.path.join(os.path.dirname(__file__), "BARN_dataset")
    output_path = os.path.join(os.path.dirname(__file__), "expert_data.npz")

    all_lidar = []
    all_goal = []
    all_commands = []

    num_worlds = 300
    for idx in range(num_worlds):
        result = process_world(idx, dataset_dir)
        if result is None:
            print(f"  World {idx}: skipped (invalid path)")
            continue

        lidar, goal_features, commands = result
        all_lidar.append(lidar)
        all_goal.append(goal_features)
        all_commands.append(commands)

        if (idx + 1) % 50 == 0:
            total = sum(len(l) for l in all_lidar)
            print(f"  Processed {idx + 1}/{num_worlds} worlds, {total} samples so far")

    all_lidar = np.concatenate(all_lidar, axis=0)
    all_goal = np.concatenate(all_goal, axis=0)
    all_commands = np.concatenate(all_commands, axis=0)

    print(f"\nDataset summary:")
    print(f"  Total samples: {len(all_lidar)}")
    print(f"  LiDAR shape: {all_lidar.shape}")
    print(f"  Goal features shape: {all_goal.shape}")
    print(f"  Commands shape: {all_commands.shape}")

    np.savez_compressed(output_path,
                        lidar=all_lidar,
                        goal_features=all_goal,
                        commands=all_commands)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
