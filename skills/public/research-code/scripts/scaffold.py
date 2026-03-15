"""Research code scaffolding generator.

Generates a complete research project structure from a paper's methodology section.

Usage:
    python scaffold.py --name <project_name> --paradigm <ml|stats|simulation> --output <path>
"""

import argparse
import os


TEMPLATES = {
    "ml": {
        "dirs": [
            "src/models", "src/data", "src/trainers", "src/evaluation",
            "configs", "scripts", "tests", "notebooks", "data/raw", "data/processed",
        ],
        "files": {
            "src/__init__.py": "",
            "src/models/__init__.py": "",
            "src/models/base.py": '''"""Base model interface."""
from abc import ABC, abstractmethod

import torch.nn as nn


class BaseModel(ABC, nn.Module):
    """Abstract base class for all research models."""

    @abstractmethod
    def forward(self, x):
        ...

    @property
    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    @property
    def num_trainable_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
''',
            "src/data/__init__.py": "",
            "src/data/dataset.py": '''"""Dataset loading and preprocessing."""
import pandas as pd
from torch.utils.data import Dataset


class ResearchDataset(Dataset):
    def __init__(self, data_path, split="train", transform=None):
        self.data = pd.read_csv(data_path)
        self.transform = transform

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        sample = self.data.iloc[idx]
        if self.transform:
            sample = self.transform(sample)
        return sample
''',
            "src/trainers/__init__.py": "",
            "src/evaluation/__init__.py": "",
            "configs/default.yaml": '''experiment:
  name: "experiment_001"
  seed: 42
  device: "cuda"

model:
  type: "baseline"
  hidden_dim: 256
  dropout: 0.1

training:
  epochs: 100
  batch_size: 32
  learning_rate: 1e-3
  weight_decay: 1e-5
  scheduler: "cosine"
  warmup_steps: 100
  gradient_clip: 1.0

data:
  train_path: "data/processed/train.csv"
  val_path: "data/processed/val.csv"
  test_path: "data/processed/test.csv"

logging:
  log_dir: "logs"
  save_every: 10
  eval_every: 5
''',
            "scripts/train.py": '''"""Training script with reproducibility guarantees."""
import argparse
import random

import numpy as np
import torch
import yaml


def set_seed(seed):
    """Set all random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    set_seed(config["experiment"]["seed"])
    print(f"Starting experiment: {config[\'experiment\'][\'name\']}")
    print(f"Device: {config[\'experiment\'][\'device\']}")
    print(f"Seed: {config[\'experiment\'][\'seed\']}")


if __name__ == "__main__":
    main()
''',
            "scripts/evaluate.py": '''"""Evaluation script."""
import argparse

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--checkpoint", required=True)
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    print(f"Evaluating checkpoint: {args.checkpoint}")


if __name__ == "__main__":
    main()
''',
            "tests/__init__.py": "",
            "tests/test_model.py": '''"""Model unit tests."""
import torch


def test_model_output_shape():
    """Test that model output has expected shape."""
    pass


def test_model_determinism():
    """Test that model produces same output with same seed."""
    pass


def test_gradient_flow():
    """Test that gradients flow through all parameters."""
    pass
''',
            "requirements.txt": '''torch>=2.0.0
numpy>=1.24.0
pandas>=2.0.0
scikit-learn>=1.3.0
pyyaml>=6.0
matplotlib>=3.7.0
tensorboard>=2.14.0
tqdm>=4.65.0
''',
            "Makefile": '''train:
\tpython scripts/train.py --config configs/default.yaml

evaluate:
\tpython scripts/evaluate.py --config configs/default.yaml --checkpoint $(CKPT)

test:
\tpython -m pytest tests/ -v

lint:
\truff check src/ scripts/

.PHONY: train evaluate test lint
''',
            "README.md": '''# Research Project

## Setup

```bash
pip install -r requirements.txt
```

## Training

```bash
make train
```

## Evaluation

```bash
make evaluate CKPT=path/to/checkpoint.pt
```

## Testing

```bash
make test
```
''',
        },
    },
    "stats": {
        "dirs": [
            "src", "data/raw", "data/processed", "outputs/figures", "outputs/tables",
            "scripts", "tests", "notebooks",
        ],
        "files": {
            "src/__init__.py": "",
            "src/analysis.py": '''"""Main analysis module."""
import pandas as pd
import scipy.stats as stats


def load_and_clean(path):
    """Load data and perform basic cleaning."""
    df = pd.read_csv(path)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    print(f"Missing values: {df.isnull().sum().sum()}")
    return df
''',
            "configs/analysis.yaml": '''data:
  input_path: "data/raw/dataset.csv"
  output_dir: "outputs"

analysis:
  alpha: 0.05
  bootstrap_n: 2000
  random_seed: 42

figures:
  dpi: 300
  format: "pdf"
  style: "seaborn-v0_8-whitegrid"
''',
            "scripts/run_analysis.py": '''"""Run complete analysis pipeline."""
import argparse

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/analysis.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    print(f"Running analysis with alpha={config[\'analysis\'][\'alpha\']}")


if __name__ == "__main__":
    main()
''',
            "requirements.txt": '''numpy>=1.24.0
pandas>=2.0.0
scipy>=1.10.0
statsmodels>=0.14.0
scikit-learn>=1.3.0
pingouin>=0.5.3
matplotlib>=3.7.0
seaborn>=0.12.0
pyyaml>=6.0
openpyxl>=3.1.0
''',
            "Makefile": '''analyze:
\tpython scripts/run_analysis.py --config configs/analysis.yaml

test:
\tpython -m pytest tests/ -v

.PHONY: analyze test
''',
        },
    },
    "simulation": {
        "dirs": [
            "src", "configs", "scripts", "tests", "outputs/results", "outputs/figures",
        ],
        "files": {
            "src/__init__.py": "",
            "src/simulator.py": '''"""Base simulation framework."""
from abc import ABC, abstractmethod


class BaseSimulator(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def step(self, state):
        ...

    @abstractmethod
    def run(self, n_steps):
        ...
''',
            "configs/default.yaml": '''simulation:
  n_steps: 10000
  seed: 42
  dt: 0.01

parameters:
  # Add simulation-specific parameters here
  param_a: 1.0
  param_b: 0.5
''',
            "requirements.txt": '''numpy>=1.24.0
scipy>=1.10.0
matplotlib>=3.7.0
pyyaml>=6.0
tqdm>=4.65.0
''',
        },
    },
}


def create_scaffold(name, paradigm, output_path):
    """Create a research project scaffold."""
    template = TEMPLATES.get(paradigm)
    if not template:
        print(f"Unknown paradigm: {paradigm}. Available: {list(TEMPLATES.keys())}")
        return

    project_root = os.path.join(output_path, name)
    os.makedirs(project_root, exist_ok=True)

    for d in template["dirs"]:
        os.makedirs(os.path.join(project_root, d), exist_ok=True)

    for filepath, content in template["files"].items():
        full_path = os.path.join(project_root, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    print(f"Project scaffold created at: {project_root}")
    print(f"Paradigm: {paradigm}")
    print(f"Structure:")
    for d in sorted(template["dirs"]):
        print(f"  {d}/")
    for f in sorted(template["files"].keys()):
        print(f"  {f}")


def main():
    parser = argparse.ArgumentParser(description="Research code scaffolding generator")
    parser.add_argument("--name", required=True, help="Project name")
    parser.add_argument("--paradigm", default="ml", choices=list(TEMPLATES.keys()), help="Research paradigm")
    parser.add_argument("--output", default="/mnt/user-data/outputs", help="Output directory")
    args = parser.parse_args()
    create_scaffold(args.name, args.paradigm, args.output)


if __name__ == "__main__":
    main()
