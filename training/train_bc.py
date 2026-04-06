"""
Train Behavior Cloning model on expert data.

Data augmentation:
  - Gaussian noise on LiDAR (sigma=0.05)
  - Random ray dropout (5-10%)
  - Mirror augmentation (flip scan, negate omega)
  - Goal angle jitter (±5 degrees)
"""

import os
import argparse
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

from bc_model import BCModel


class ExpertDataset(Dataset):
    def __init__(self, lidar, goal_features, commands, augment=True):
        self.lidar = lidar.astype(np.float32)
        self.goal_features = goal_features.astype(np.float32)
        self.commands = commands.astype(np.float32)
        self.augment = augment

    def __len__(self):
        return len(self.lidar)

    def __getitem__(self, idx):
        lidar = self.lidar[idx].copy()
        goal = self.goal_features[idx].copy()
        cmd = self.commands[idx].copy()

        if self.augment:
            lidar, goal, cmd = self._augment(lidar, goal, cmd)

        return (
            torch.from_numpy(lidar),
            torch.from_numpy(goal),
            torch.from_numpy(cmd),
        )

    def _augment(self, lidar, goal, cmd):
        # 1. Gaussian noise on LiDAR
        if np.random.rand() < 0.5:
            noise = np.random.normal(0, 0.05, lidar.shape).astype(np.float32)
            lidar = np.clip(lidar + noise, 0, 10.0)

        # 2. Random ray dropout (5-10%)
        if np.random.rand() < 0.3:
            drop_rate = np.random.uniform(0.05, 0.10)
            drop_mask = np.random.rand(len(lidar)) < drop_rate
            lidar[drop_mask] = 10.0  # Set dropped rays to max range

        # 3. Mirror augmentation (flip scan, negate omega and theta_goal)
        if np.random.rand() < 0.5:
            lidar = lidar[::-1].copy()
            goal[1] = -goal[1]   # negate theta_goal
            goal[3] = -goal[3]   # negate omega_current
            cmd[1] = -cmd[1]     # negate omega*

        # 4. Goal angle jitter (±5 degrees)
        if np.random.rand() < 0.3:
            jitter = np.random.uniform(-np.radians(5), np.radians(5))
            goal[1] += jitter

        return lidar, goal, cmd


def train(args):
    # Prefer MPS (Apple Silicon GPU) for training
    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    print(f"Using device: {device}")

    # Load data
    data = np.load(args.data_path)
    lidar = data["lidar"]
    goal_features = data["goal_features"]
    commands = data["commands"]
    print(f"Loaded {len(lidar)} samples")

    # Train/val split (90/10)
    n = len(lidar)
    indices = np.random.permutation(n)
    split = int(0.9 * n)
    train_idx, val_idx = indices[:split], indices[split:]

    train_dataset = ExpertDataset(
        lidar[train_idx], goal_features[train_idx], commands[train_idx], augment=True
    )
    val_dataset = ExpertDataset(
        lidar[val_idx], goal_features[val_idx], commands[val_idx], augment=False
    )

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size,
                              shuffle=True, num_workers=0, drop_last=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size,
                            shuffle=False, num_workers=0)

    # Model
    model = BCModel().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=1e-6
    )

    # Loss: MSE on (v, omega) with higher weight on omega
    v_weight = 1.0
    omega_weight = 2.0

    best_val_loss = float("inf")
    save_dir = os.path.dirname(os.path.abspath(__file__))

    epoch_pbar = tqdm(range(args.epochs), desc="Training", unit="epoch")
    for epoch in epoch_pbar:
        # Training
        model.train()
        train_losses = []
        batch_pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{args.epochs}",
                          leave=False, unit="batch")
        for lidar_batch, goal_batch, cmd_batch in batch_pbar:
            lidar_batch = lidar_batch.to(device)
            goal_batch = goal_batch.to(device)
            cmd_batch = cmd_batch.to(device)

            pred = model(lidar_batch, goal_batch)

            loss_v = nn.functional.mse_loss(pred[:, 0], cmd_batch[:, 0])
            loss_omega = nn.functional.mse_loss(pred[:, 1], cmd_batch[:, 1])
            loss = v_weight * loss_v + omega_weight * loss_omega

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            train_losses.append(loss.item())
            batch_pbar.set_postfix(loss=f"{loss.item():.4f}")

        scheduler.step()

        # Validation
        model.eval()
        val_losses = []
        val_v_losses = []
        val_omega_losses = []
        with torch.no_grad():
            for lidar_batch, goal_batch, cmd_batch in tqdm(val_loader, desc="Validating",
                                                           leave=False, unit="batch"):
                lidar_batch = lidar_batch.to(device)
                goal_batch = goal_batch.to(device)
                cmd_batch = cmd_batch.to(device)

                pred = model(lidar_batch, goal_batch)
                loss_v = nn.functional.mse_loss(pred[:, 0], cmd_batch[:, 0])
                loss_omega = nn.functional.mse_loss(pred[:, 1], cmd_batch[:, 1])
                loss = v_weight * loss_v + omega_weight * loss_omega

                val_losses.append(loss.item())
                val_v_losses.append(loss_v.item())
                val_omega_losses.append(loss_omega.item())

        avg_train = np.mean(train_losses)
        avg_val = np.mean(val_losses)
        avg_val_v = np.mean(val_v_losses)
        avg_val_omega = np.mean(val_omega_losses)

        epoch_pbar.set_postfix(train=f"{avg_train:.4f}", val=f"{avg_val:.4f}",
                               v=f"{avg_val_v:.4f}", omega=f"{avg_val_omega:.4f}")

        # Save best model
        if avg_val < best_val_loss:
            best_val_loss = avg_val
            torch.save(model.state_dict(), os.path.join(save_dir, "bc_model_best.pt"))
            print(f"  -> Saved best model (val_loss={avg_val:.4f})")

    # Save final model
    torch.save(model.state_dict(), os.path.join(save_dir, "bc_model_final.pt"))
    print(f"\nTraining complete. Best val loss: {best_val_loss:.4f}")

    # Export to ONNX
    try:
        model.load_state_dict(torch.load(os.path.join(save_dir, "bc_model_best.pt"),
                                         weights_only=True))
        model.cpu()
        model.export_onnx(os.path.join(save_dir, "bc_model.onnx"))
    except Exception as e:
        print(f"\nONNX export failed: {e}")
        print("Install onnx with: pip install onnx")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_path", type=str, default="expert_data.npz")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()
    train(args)
