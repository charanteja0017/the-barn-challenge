#!/usr/bin/env python3
"""
visualize_trajectory.py - Generate an animated video of the robot's trajectory
through a BARN obstacle world.

Usage:
    python3 visualize_trajectory.py --trajectory trajectory_world_0.npy --world_idx 0
    python3 visualize_trajectory.py --trajectory trajectory_world_0.npy --world_idx 0 --output video.mp4

This loads the saved trajectory (from run.py --save_trajectory) and the BARN
world obstacle data, then creates an animated bird's-eye view video.
"""

import argparse
import os
import sys
import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for headless environments
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    from matplotlib.patches import Circle
    from matplotlib.collections import PatchCollection
except ImportError:
    print("ERROR: matplotlib is required. Install with: pip3 install matplotlib")
    sys.exit(1)


RADIUS = 0.075  # obstacle radius in the BARN dataset


def path_coord_to_gazebo_coord(x, y):
    """Convert BARN grid coordinates to Gazebo world coordinates."""
    r_shift = -RADIUS - (30 * RADIUS * 2)
    c_shift = RADIUS + 5
    gazebo_x = x * (RADIUS * 2) + r_shift
    gazebo_y = y * (RADIUS * 2) + c_shift
    return gazebo_x, gazebo_y


def load_world_obstacles(world_idx, base_path=None):
    """Load obstacle positions for a given BARN world index."""
    if base_path is None:
        # Try to find jackal_helper in common locations
        candidates = [
            os.path.join(os.path.dirname(__file__), "jackal_helper"),
            "/jackal_ws/src/jackal_helper",
            os.path.join(os.path.dirname(__file__), "jackal_helper"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                base_path = c
                break

    if base_path is None:
        print("WARNING: Could not find jackal_helper. Plotting trajectory only (no obstacles).")
        return None

    if world_idx < 300:
        path_file = os.path.join(base_path, "worlds", "BARN", "path_files", f"path_{world_idx}.npy")
    else:
        print("INFO: DynaBARN worlds don't have static obstacle files. Plotting trajectory only.")
        return None

    if not os.path.exists(path_file):
        print(f"WARNING: Path file not found: {path_file}. Plotting trajectory only.")
        return None

    return np.load(path_file)


def create_trajectory_animation(trajectory, world_idx, optimal_path=None, output_file="trajectory.mp4",
                                 fps=20, trail_length=50):
    """
    Create an animated video of the robot trajectory.

    Args:
        trajectory: Nx3 array of [time, x, y]
        world_idx: BARN world index (for title)
        optimal_path: Optional path array for reference
        output_file: Output video filename
        fps: Frames per second
        trail_length: Number of past positions to show as trail
    """
    times = trajectory[:, 0]
    xs = trajectory[:, 1]
    ys = trajectory[:, 2]

    # Determine init and goal positions
    if world_idx < 300:
        init_pos = (-2.25, 3)
        goal_pos = (-2.25, 13)  # init + goal offset (0, 10)
    else:
        init_pos = (11, 0)
        goal_pos = (-9, 0)  # init + goal offset (-20, 0)

    # Set up figure
    fig, ax = plt.subplots(1, 1, figsize=(8, 10), dpi=100)
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')

    # Plot boundaries with some padding
    x_min = min(xs.min(), init_pos[0], goal_pos[0]) - 1.5
    x_max = max(xs.max(), init_pos[0], goal_pos[0]) + 1.5
    y_min = min(ys.min(), init_pos[1], goal_pos[1]) - 1.5
    y_max = max(ys.max(), init_pos[1], goal_pos[1]) + 1.5
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect('equal')

    # Plot optimal path if available
    if optimal_path is not None:
        opt_gazebo = np.array([path_coord_to_gazebo_coord(p[0], p[1]) for p in optimal_path])
        ax.plot(opt_gazebo[:, 0], opt_gazebo[:, 1], 'o', color='#e94560',
                markersize=1.5, alpha=0.3, label='Obstacles/Path')

    # Start and goal markers
    ax.plot(*init_pos, 's', color='#00ff88', markersize=14, markeredgecolor='white',
            markeredgewidth=2, label='Start', zorder=10)
    ax.plot(*goal_pos, '*', color='#ffdd44', markersize=18, markeredgecolor='white',
            markeredgewidth=1.5, label='Goal', zorder=10)

    # Full trajectory (faint)
    ax.plot(xs, ys, '-', color='#0f3460', linewidth=1, alpha=0.3)

    # Animated elements
    trail_line, = ax.plot([], [], '-', color='#e94560', linewidth=2.5, alpha=0.8)
    robot_dot, = ax.plot([], [], 'o', color='#00ff88', markersize=10,
                         markeredgecolor='white', markeredgewidth=2, zorder=15)

    # Title and labels
    title_text = ax.set_title(f'BARN World {world_idx}  |  t = 0.00s',
                               fontsize=14, fontweight='bold', color='white', pad=15)
    ax.set_xlabel('X (m)', color='#aaa', fontsize=11)
    ax.set_ylabel('Y (m)', color='#aaa', fontsize=11)
    ax.tick_params(colors='#666')
    for spine in ax.spines.values():
        spine.set_color('#333')

    # Legend
    legend = ax.legend(loc='upper right', fontsize=9, facecolor='#1a1a2e',
                       edgecolor='#333', labelcolor='white')

    # Distance indicator
    dist_text = ax.text(0.02, 0.02, '', transform=ax.transAxes, fontsize=10,
                        color='#aaa', verticalalignment='bottom',
                        fontfamily='monospace')

    # Subsample frames if trajectory is very long
    n_frames = len(xs)
    max_frames = fps * 30  # cap at 30 seconds of video
    if n_frames > max_frames:
        frame_indices = np.linspace(0, n_frames - 1, max_frames, dtype=int)
    else:
        frame_indices = np.arange(n_frames)

    def init():
        trail_line.set_data([], [])
        robot_dot.set_data([], [])
        return trail_line, robot_dot, title_text, dist_text

    def animate(frame_num):
        idx = frame_indices[frame_num]
        t = times[idx]

        # Trail
        start = max(0, idx - trail_length)
        trail_line.set_data(xs[start:idx + 1], ys[start:idx + 1])

        # Robot position
        robot_dot.set_data([xs[idx]], [ys[idx]])

        # Update title with time
        title_text.set_text(f'BARN World {world_idx}  |  t = {t:.2f}s')

        # Distance to goal
        dist = np.sqrt((xs[idx] - goal_pos[0])**2 + (ys[idx] - goal_pos[1])**2)
        dist_text.set_text(f'Dist to goal: {dist:.2f}m')

        return trail_line, robot_dot, title_text, dist_text

    anim = animation.FuncAnimation(fig, animate, init_func=init,
                                    frames=len(frame_indices),
                                    interval=1000 / fps, blit=True)

    # Save
    print(f"Saving animation to {output_file} ({len(frame_indices)} frames @ {fps}fps)...")
    try:
        writer = animation.FFMpegWriter(fps=fps, bitrate=2000,
                                         extra_args=['-pix_fmt', 'yuv420p'])
        anim.save(output_file, writer=writer)
    except (FileNotFoundError, RuntimeError):
        print("ffmpeg not found, trying Pillow writer (.gif)...")
        gif_file = output_file.rsplit('.', 1)[0] + '.gif'
        anim.save(gif_file, writer='pillow', fps=fps)
        output_file = gif_file

    plt.close(fig)
    print(f"Done! Saved: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description='Visualize BARN navigation trajectory')
    parser.add_argument('--trajectory', type=str, required=True,
                        help='Path to trajectory .npy file (saved by run.py --save_trajectory)')
    parser.add_argument('--world_idx', type=int, required=True,
                        help='BARN world index (for obstacle data and title)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output video file (default: trajectory_world_<idx>.mp4)')
    parser.add_argument('--fps', type=int, default=20, help='Frames per second (default: 20)')
    parser.add_argument('--trail', type=int, default=50,
                        help='Number of past positions to show as trail (default: 50)')
    parser.add_argument('--jackal_helper', type=str, default=None,
                        help='Path to jackal_helper package (for obstacle data)')
    args = parser.parse_args()

    if args.output is None:
        args.output = f"trajectory_world_{args.world_idx}.mp4"

    # Load trajectory
    print(f"Loading trajectory from {args.trajectory}...")
    trajectory = np.load(args.trajectory)
    print(f"  {len(trajectory)} data points, time range: {trajectory[0, 0]:.2f}s - {trajectory[-1, 0]:.2f}s")

    # Load obstacle/path data
    optimal_path = load_world_obstacles(args.world_idx, args.jackal_helper)

    # Create animation
    create_trajectory_animation(
        trajectory=trajectory,
        world_idx=args.world_idx,
        optimal_path=optimal_path,
        output_file=args.output,
        fps=args.fps,
        trail_length=args.trail
    )


if __name__ == '__main__':
    main()
