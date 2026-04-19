# Minimal long-run training script for YOLOv8s thermal person detection.

import argparse
from pathlib import Path
from ultralytics import YOLO
import torch


def train(data_yaml: str, model: str = "s", epochs: int = 500, imgsz: int = 640,
          batch: int = 24, name: str = "thermalCrowdCounting", patience: int = 50,
          workers: int = 8, seed: int = 0):
    """Train YOLO model for thermal image person detection."""
    data_path = Path(data_yaml)
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset config not found: {data_yaml}")

    if model.endswith('.pt') and Path(model).exists():
        model_path = model
        print(f"Resuming from checkpoint: {model_path}")
    else:
        model_path = f"yolov8{model}.pt"
        print(f"Initializing model: {model_path}")

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    device_label = torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'

    print(f"\nTraining: {name}")
    print(f"  Device:  {device_label}")
    print(f"  Dataset: {data_yaml}")
    print(f"  Epochs: {epochs}, Batch: {batch}, Image size: {imgsz}")
    print(f"  Patience: {patience}, Workers: {workers}, Seed: {seed}\n")

    yolo_model = YOLO(model_path)
    yolo_model.train(
        data=str(data_path),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        name=name,
        project='models',
        device=device,
        patience=patience,
        workers=workers,
        seed=seed,
        cos_lr=True,
        amp=True,
        deterministic=True,
        exist_ok=True,
    )

    print(f"\nTraining completed.")
    print(f"  Best model: {yolo_model.trainer.best}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Long-run YOLOv8 training for thermal person detection")
    parser.add_argument("--data", type=str, required=True, help="Path to dataset YAML file")
    parser.add_argument("--model", type=str, default="s", help="Model size (n, s, m, l, x) or checkpoint path")
    parser.add_argument("--epochs", type=int, default=500, help="Number of training epochs")
    parser.add_argument("--batch", type=int, default=24, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size for training")
    parser.add_argument("--name", type=str, default="thermalCrowdCounting", help="Training run name")
    parser.add_argument("--patience", type=int, default=50, help="Early stopping patience (0 to disable)")
    parser.add_argument("--workers", type=int, default=8, help="Dataloader workers")
    parser.add_argument("--seed", type=int, default=0, help="Random seed")

    args = parser.parse_args()
    train(args.data, args.model, args.epochs, args.imgsz, args.batch,
          args.name, args.patience, args.workers, args.seed)
