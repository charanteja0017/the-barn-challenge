# -*- coding: utf-8 -*-
"""
BC Navigation Node for BARN Challenge.

Subscribes to /front/scan (LiDAR) and publishes to /cmd_vel.
Includes safety layer and stuck recovery FSM per methodology.

Algorithm (per timestep):
  1. (vm, wm) = BCModel(LiDAR, goal, vel)
  2. dmin = min(LiDAR[front ± 60°])
  3. if dmin < 0.25m: v=0, rotate away
  4. elif dmin < 0.45m: v = vm * (dmin - 0.20) / 0.25
  5. else: trust model
  6. if stuck (|v| < 0.05 for > 2s): back up + rotate (recovery FSM)
  7. Publish (v, omega) to /cmd_vel
"""

import os
import time
import math
import numpy as np
import torch

import rospy
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from tf.transformations import euler_from_quaternion

from bc_model import BCModel


class RecoveryState:
    NONE = 0
    BACKUP = 1
    ROTATE = 2


class BCNavigator:
    def __init__(self, model_path, goal_x, goal_y):
        # Load model
        self.device = torch.device("cpu")
        self.model = BCModel()
        state = torch.load(model_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state)
        self.model.eval()

        # Goal in odom frame
        self.goal_x = goal_x
        self.goal_y = goal_y

        # Robot state
        self.robot_x = 0.0
        self.robot_y = 0.0
        self.robot_yaw = 0.0
        self.current_v = 0.0
        self.current_omega = 0.0
        self.last_lidar = None

        # Recovery FSM
        self.recovery_state = RecoveryState.NONE
        self.recovery_start_time = None
        self.stuck_start_time = None
        self.STUCK_THRESHOLD = 2.0  # seconds
        self.BACKUP_DURATION = 1.0
        self.ROTATE_DURATION = 1.5

        # Publisher
        self.cmd_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=1)

        # Subscribers
        rospy.Subscriber("/front/scan", LaserScan, self.lidar_callback, queue_size=1)
        rospy.Subscriber("/odometry/filtered", Odometry, self.odom_callback, queue_size=1)

    def odom_callback(self, msg):
        self.robot_x = msg.pose.pose.position.x
        self.robot_y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        _, _, self.robot_yaw = euler_from_quaternion([q.x, q.y, q.z, q.w])
        self.current_v = msg.twist.twist.linear.x
        self.current_omega = msg.twist.twist.angular.z

    def lidar_callback(self, msg):
        self.last_lidar = np.array(msg.ranges, dtype=np.float32)
        # Replace inf/nan with max range
        self.last_lidar = np.where(
            np.isfinite(self.last_lidar), self.last_lidar, 10.0
        )

    def compute_goal_features(self):
        """Compute (d_goal, theta_goal, v_current, omega_current)."""
        dx = self.goal_x - self.robot_x
        dy = self.goal_y - self.robot_y
        d_goal = math.sqrt(dx ** 2 + dy ** 2)

        angle_to_goal = math.atan2(dy, dx)
        theta_goal = angle_to_goal - self.robot_yaw
        # Normalize to [-pi, pi]
        theta_goal = (theta_goal + math.pi) % (2 * math.pi) - math.pi

        return np.array([d_goal, theta_goal, self.current_v, self.current_omega],
                        dtype=np.float32)

    def get_front_min_distance(self, lidar):
        """Get minimum distance in front arc (±60 degrees)."""
        n = len(lidar)
        # Assuming 360° scan, front is at index n//2 for ust10 or index 0
        # ±60° = ±(n * 60/360) indices
        arc = int(n * 60.0 / 360.0)
        center = n // 2
        front_slice = np.concatenate([
            lidar[max(0, center - arc):center],
            lidar[center:min(n, center + arc)]
        ])
        return np.min(front_slice) if len(front_slice) > 0 else 10.0

    def find_clear_direction(self, lidar):
        """Find the angular direction with most clearance for rotation."""
        n = len(lidar)
        # Check left half vs right half
        left_avg = np.mean(lidar[:n // 2])
        right_avg = np.mean(lidar[n // 2:])
        # Rotate towards the side with more clearance
        return 1.0 if left_avg > right_avg else -1.0

    @torch.no_grad()
    def step(self):
        """One navigation step. Returns (v, omega) to publish."""
        if self.last_lidar is None:
            return 0.0, 0.0

        lidar = self.last_lidar.copy()
        now = time.time()

        # --- Recovery FSM ---
        if self.recovery_state == RecoveryState.BACKUP:
            elapsed = now - self.recovery_start_time
            if elapsed < self.BACKUP_DURATION:
                return -0.3, 0.0
            else:
                self.recovery_state = RecoveryState.ROTATE
                self.recovery_start_time = now
                self.rotate_dir = self.find_clear_direction(lidar)
                return 0.0, self.rotate_dir * 1.0

        elif self.recovery_state == RecoveryState.ROTATE:
            elapsed = now - self.recovery_start_time
            if elapsed < self.ROTATE_DURATION:
                return 0.0, self.rotate_dir * 1.0
            else:
                self.recovery_state = RecoveryState.NONE
                self.stuck_start_time = None

        # --- Model inference ---
        # Resample LiDAR to 720 rays if needed
        if len(lidar) != 720:
            lidar = np.interp(
                np.linspace(0, len(lidar) - 1, 720),
                np.arange(len(lidar)),
                lidar
            ).astype(np.float32)

        goal_features = self.compute_goal_features()

        lidar_t = torch.from_numpy(lidar).unsqueeze(0)
        goal_t = torch.from_numpy(goal_features).unsqueeze(0)
        pred = self.model(lidar_t, goal_t)
        vm = pred[0, 0].item()
        wm = pred[0, 1].item()

        # --- Safety layer ---
        dmin = self.get_front_min_distance(lidar)

        if dmin < 0.25:
            # Emergency: stop and rotate away
            v = 0.0
            omega = self.find_clear_direction(lidar) * 1.5
        elif dmin < 0.45:
            # Slow down proportionally
            scale = (dmin - 0.20) / 0.25
            v = vm * max(scale, 0.0)
            omega = wm
        else:
            # Trust model
            v = vm
            omega = wm

        # --- Stuck detection ---
        if abs(v) < 0.05 and abs(self.current_v) < 0.05:
            if self.stuck_start_time is None:
                self.stuck_start_time = now
            elif now - self.stuck_start_time > self.STUCK_THRESHOLD:
                rospy.logwarn("Stuck detected! Entering recovery...")
                self.recovery_state = RecoveryState.BACKUP
                self.recovery_start_time = now
                return -0.3, 0.0
        else:
            self.stuck_start_time = None

        return v, omega

    def run(self):
        """Main loop at 10 Hz."""
        rate = rospy.Rate(10)
        while not rospy.is_shutdown():
            v, omega = self.step()

            cmd = Twist()
            cmd.linear.x = float(np.clip(v, -0.5, 2.0))
            cmd.angular.z = float(np.clip(omega, -2.0, 2.0))
            self.cmd_pub.publish(cmd)

            rate.sleep()


def main():
    rospy.init_node("bc_navigator", anonymous=True)

    model_path = rospy.get_param("~model_path",
                                 os.path.join(os.path.dirname(__file__),
                                              "bc_model_best.pt"))
    goal_x = rospy.get_param("~goal_x", 0.0)
    goal_y = rospy.get_param("~goal_y", 10.0)

    navigator = BCNavigator(model_path, goal_x, goal_y)
    rospy.loginfo(f"BC Navigator started. Goal: ({goal_x}, {goal_y})")
    navigator.run()


if __name__ == "__main__":
    main()
