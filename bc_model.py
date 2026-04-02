"""
Behavior Cloning model for BARN Challenge navigation.
1D CNN with residual connections, ~300K parameters.
Input: LiDAR (720), goal distance, goal angle, current v, current omega
Output: v*, omega*
"""

import torch
import torch.nn as nn


class ResBlock1D(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(channels)
        self.conv2 = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm1d(channels)

    def forward(self, x):
        residual = x
        x = torch.relu(self.bn1(self.conv1(x)))
        x = self.bn2(self.conv2(x))
        return torch.relu(x + residual)


class BCModel(nn.Module):
    """
    Architecture:
      LiDAR (720) -> Conv1D layers with residual connections -> Global Avg Pool
      Concatenate with goal features (d_goal, theta_goal, v, omega)
      -> MLP head -> (v*, omega*)
    """

    def __init__(self, lidar_dim=720, goal_dim=4, hidden_dim=256):
        super().__init__()

        # LiDAR encoder: 3 Conv1D layers with increasing channels
        self.lidar_encoder = nn.Sequential(
            # Layer 1: 1 -> 64 channels
            nn.Conv1d(1, 64, kernel_size=5, stride=2, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            ResBlock1D(64),
            # Layer 2: 64 -> 128 channels
            nn.Conv1d(64, 128, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            ResBlock1D(128),
            # Layer 3: 128 -> 128 channels
            nn.Conv1d(128, 128, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            ResBlock1D(128),
            # Global average pooling
            nn.AdaptiveAvgPool1d(1),
        )

        # MLP head: lidar features (128) + goal features (4) -> (v, omega)
        self.mlp = nn.Sequential(
            nn.Linear(128 + goal_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(64, 2),  # (v, omega)
        )

        # Output activation: v in [0, 2.0], omega in [-2.0, 2.0]
        self.v_max = 2.0
        self.omega_max = 2.0

    def forward(self, lidar, goal_features):
        """
        Args:
            lidar: (batch, 720) raw LiDAR ranges
            goal_features: (batch, 4) [d_goal, theta_goal, v_current, omega_current]
        Returns:
            (batch, 2) [v*, omega*]
        """
        # Normalize LiDAR: clip to max range and scale
        lidar = torch.clamp(lidar, 0.0, 10.0) / 10.0

        # Reshape for Conv1D: (batch, 1, 720)
        x = lidar.unsqueeze(1)
        x = self.lidar_encoder(x)
        x = x.squeeze(-1)  # (batch, 128)

        # Concatenate with goal features
        x = torch.cat([x, goal_features], dim=1)

        # MLP head
        out = self.mlp(x)

        # Constrain outputs
        v = torch.sigmoid(out[:, 0]) * self.v_max
        omega = torch.tanh(out[:, 1]) * self.omega_max

        return torch.stack([v, omega], dim=1)

    def export_onnx(self, path="bc_model.onnx"):
        """Export model to ONNX for fast CPU inference."""
        self.eval()
        dummy_lidar = torch.randn(1, 720)
        dummy_goal = torch.randn(1, 4)
        torch.onnx.export(
            self,
            (dummy_lidar, dummy_goal),
            path,
            input_names=["lidar", "goal_features"],
            output_names=["commands"],
            dynamic_axes={
                "lidar": {0: "batch"},
                "goal_features": {0: "batch"},
                "commands": {0: "batch"},
            },
            opset_version=11,
        )
        print(f"Exported ONNX model to {path}")


def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


if __name__ == "__main__":
    model = BCModel()
    print(f"Model parameters: {count_parameters(model):,}")
    # Quick forward pass test
    lidar = torch.randn(4, 720)
    goal = torch.randn(4, 4)
    out = model(lidar, goal)
    print(f"Input: lidar {lidar.shape}, goal {goal.shape}")
    print(f"Output: {out.shape} -> {out}")
