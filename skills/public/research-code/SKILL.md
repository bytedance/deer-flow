---
name: research-code
description: Use this skill when the user needs to reproduce a paper's algorithm, generate experiment code scaffolding, create ML training pipelines, set up research project structure, or ensure code reproducibility. Covers paper algorithm to code translation, experiment boilerplate generation, research project templates, benchmark testing, and scientific computing best practices. Trigger on queries like "implement this algorithm", "reproduce this paper", "create experiment code", "ML pipeline scaffold", "research project setup", or any request involving translating research into code.
---

# Research Code Skill

## Overview

This skill bridges the gap between research papers and working code. It provides workflows for translating paper algorithms into implementations, generating experiment scaffolding, creating reproducible research project structures, and running benchmark evaluations.

## When to Use This Skill

**Always load this skill when:**

- User wants to reproduce or implement an algorithm from a paper
- User needs ML training/evaluation pipeline code
- User wants to set up a research project structure
- User needs experiment boilerplate with proper configuration
- User asks for help with benchmarking or performance testing
- User wants code quality tools for research code (tests, docs, types)

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Paper → Code** | Translate algorithm descriptions/pseudocode into Python |
| **Project Scaffold** | Generate research project directory structure |
| **ML Pipeline** | Training, evaluation, and inference pipeline templates |
| **Config Management** | Hydra/OmegaConf experiment configuration |
| **Reproducibility** | Seed management, requirements, Dockerfile |
| **Benchmarking** | Performance testing and comparison code |
| **Code Quality** | Type hints, docstrings, unit tests for research code |
| **Documentation** | README, API docs, usage examples |

## Workflow

### Phase 0.5: Code Architecture Design

Before writing any code, design the architecture. Top-tier research code has clear design intent.

**5 Architecture Principles for Research Code**:
1. **Single Responsibility**: Each class/function does ONE thing. A `Trainer` trains; it doesn't load data.
2. **Configuration-Driven**: No magic numbers. Every hyperparameter from config files.
3. **Separation of Concerns**: Model, data, training, evaluation, visualization in separate modules.
4. **Dependency Injection**: Pass dependencies as arguments, don't hardcode them.
5. **Fail Fast**: Validate inputs at function boundaries, not deep inside computation.

**Design Pattern Toolkit**:

| Pattern | When to Use | Example |
|---------|------------|---------|
| **Registry** | Multiple model/dataset/loss variants | `@register("resnet")` → `build_model(config)` |
| **Strategy** | Swappable algorithms | `optimizer = build_optimizer(config.optimizer)` |
| **Factory** | Create objects from config | `ModelFactory.create(config.type, **config.params)` |
| **Template Method** | Shared loop with custom steps | Base `Trainer` with overridable `train_step()` |
| **Callback** | Extensible hooks | `callbacks=[Checkpoint(), EarlyStopping()]` |

**Module Dependency Rule**: `configs/ → src/models/, src/data/ → src/training/ → src/evaluation/ → scripts/`. No circular dependencies.

### Phase 0.5.5: API Design — Pit of Success

Make correct usage the easiest path, wrong usage the hardest:

- **Types as guardrails**: Use enums instead of strings — `Mode.TRAIN` not `"train"` (typos go undetected)
- **No 20-parameter constructors**: Use builder pattern or config objects — `Model(config)` not `Model(256, 3, 0.1, True, "relu")`
- **Impossible states impossible**: If two params are mutually exclusive, use separate functions, not conflicting flags
- **Sensible defaults**: `TransformerEncoder()` should work with zero arguments

### Phase 1: Paper Algorithm Reproduction

#### Step 1.1: Analyze the Algorithm

When a user provides a paper or algorithm description:

1. **Identify** the core algorithm (pseudocode, mathematical formulation, or description)
2. **Map** mathematical notation to code constructs:
   - Summations → loops or `np.sum()`
   - Matrix operations → NumPy/PyTorch operations
   - Optimization → gradient descent / scipy.optimize
   - Probability distributions → scipy.stats / torch.distributions
3. **Identify** dependencies (NumPy, PyTorch, TensorFlow, JAX, etc.)
4. **Plan** the code structure (classes, functions, modules)

#### Step 1.1.5: First-Principles Derivation

When paper pseudocode is ambiguous, derive from mathematics instead of guessing:
1. Start from the **objective function** (what's being minimized/maximized?)
2. Take **gradients analytically** — write ∂L/∂θ
3. Identify **computational structure** (gradient descent? EM? fixed-point iteration?)
4. Map each math operation → tensor operation

Example — deriving attention from "weighted average where weights depend on query-key similarity":
`scores = Q @ K.T` → `weights = softmax(scores / sqrt(d_k))` → `output = weights @ V`. The entire mechanism from one sentence.

#### Step 1.2: Generate Implementation

```python
"""
Implementation of [Algorithm Name] from:
[Author et al., "Paper Title", Venue, Year]
[DOI/arXiv link]

Key equations:
  Eq. (1): [description]
  Eq. (2): [description]
"""

import numpy as np
# or: import torch

class AlgorithmName:
    """Implementation of Algorithm Name.

    Args:
        param1: Description corresponding to paper notation (α in Eq. 1)
        param2: Description corresponding to paper notation (β in Eq. 2)

    Reference:
        Section X.Y of the original paper.
    """

    def __init__(self, param1: float = 0.1, param2: float = 0.01):
        self.param1 = param1  # α in paper
        self.param2 = param2  # β in paper

    def fit(self, X: np.ndarray, y: np.ndarray) -> "AlgorithmName":
        """Train the model.

        Implements Algorithm 1 from the paper (Section X.Y).
        """
        # Step 1: [Description matching paper]
        # Corresponds to Eq. (1)
        ...

        # Step 2: [Description matching paper]
        # Corresponds to Eq. (2)
        ...

        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Generate predictions.

        Implements inference procedure from Section X.Y.
        """
        ...
```

### Phase 1.2.5: Math-Code Isomorphism

Code structure must mirror mathematical structure — reading code = reading the algorithm:

```python
# ❌ Generic — needs comments to understand
def compute(q, k, v):
    s = q @ k.T / math.sqrt(k.shape[-1])
    return F.softmax(s, dim=-1) @ v

# ✅ Isomorphic — code reads like Eq. (3)
def scaled_dot_product_attention(query, key, value):
    d_k = key.shape[-1]
    attention_scores = query @ key.transpose(-2, -1) / math.sqrt(d_k)
    attention_weights = F.softmax(attention_scores, dim=-1)
    return attention_weights @ value
```

Rules: One equation = one function. Subscripts = dimensions (`h[i,j]`). Greek → descriptive names (`α → learning_rate`). Algorithm blocks → named methods. Self-test: can someone reconstruct the algorithm from code alone?

### Phase 1.2.7: Computational Graph Thinking

See code as a dataflow graph, not sequential instructions:

1. **Identify independent computations** → they can parallelize: `a, b = op1(x), op2(y)` not sequential
2. **Minimize data movement** — fuse ops sharing inputs: `mean, std = torch.std_mean(x)` not two passes
3. **Think in batch dimensions** — use `dim=-1` and `...` for arbitrary batch shapes, never hardcode ndim
4. **Lazy vs eager**: know when to materialize intermediates (save compute) vs recompute (save memory)

### Phase 1.3: Numerical Stability

Scientific computing code MUST be numerically stable. Apply this checklist:

| Pitfall | Symptom | Solution |
|---------|---------|---------|
| `log(softmax(x))` | NaN/Inf in loss | Use `log_softmax(x)` directly |
| `exp(x)` for large x | Inf | Log-space arithmetic: `a + log(1+exp(b-a))` |
| Sum many small floats | Precision loss | `math.fsum()` or Kahan summation |
| Division by near-zero | NaN | Add epsilon: `x / (y + 1e-8)` |
| Float32 accumulation | Drift in long chains | Float64 for accumulators, float32 for forward pass |
| Gradient explosion | NaN after few epochs | `clip_grad_norm_(params, max_norm)` |
| Large matrix inverse | Ill-conditioned | Use `torch.linalg.solve()` instead |

**Mandatory checks in critical paths**:
```python
assert not torch.isnan(loss).any(), f"NaN in loss at step {step}"
assert not torch.isinf(loss).any(), f"Inf in loss at step {step}"
```

**Dtype discipline**: `float32` for parameters (GPU efficiency), `float64` for metric accumulation, `bfloat16`/`float16` only with `torch.cuda.amp`. Always specify dtype explicitly.

### Phase 1.4: Defensive Programming

Top-tier code fails EARLY and CLEARLY.

**Input validation** at function boundaries:
```python
def train(model, dataloader, epochs: int, lr: float):
    if epochs <= 0: raise ValueError(f"epochs must be positive, got {epochs}")
    if lr <= 0 or lr > 1: raise ValueError(f"lr must be in (0,1], got {lr}")
    if len(dataloader) == 0: raise ValueError("dataloader is empty")
```

**Shape assertions** (critical for tensor code):
```python
def forward(self, x: torch.Tensor) -> torch.Tensor:
    B, C, H, W = x.shape
    assert C == self.in_channels, f"Expected {self.in_channels} channels, got {C}"
    out = self.conv(x)
    assert out.shape == (B, self.out_channels, H, W)
    return out
```

**Config validation** at startup (not mid-training):
```python
def validate_config(config: dict) -> None:
    required = ["model.type", "training.epochs", "training.lr", "data.train_path"]
    for key in required:
        parts = key.split(".")
        v = config
        for p in parts:
            if p not in v: raise KeyError(f"Missing required config: {key}")
            v = v[p]
```

### Phase 1.4.5: Failure Mode Anticipation

Before writing a function, ask "How will this fail?" and design against it:

| Failure Mode | Prevention |
|-------------|-----------|
| Silent wrong answer (broadcast mismatch) | Assert shapes after every transform |
| Data leak (train/test overlap) | `assert len(set(train_ids) & set(test_ids)) == 0` |
| NaN cascade | Check `isnan(loss)` before `.backward()` |
| Stale state (`model.eval()` forgotten) | Encapsulate in context manager |
| Config mismatch (train vs eval) | Save config hash, assert match at eval time |

**Pre-mortem**: Before writing complex code, imagine it has a bug 3 months from now. What's the most likely bug? Write a test for THAT first.

### Phase 2: Research Project Scaffolding

#### Step 2.1: Generate Project Structure

```bash
# Standard ML Research Project Structure
project_name/
├── README.md                 # Project description, setup, usage
├── requirements.txt          # Python dependencies with versions
├── setup.py                  # Package installation
├── Dockerfile                # Container for reproducibility
├── Makefile                  # Common commands
├── .gitignore
│
├── configs/                  # Experiment configurations
│   ├── default.yaml          # Default hyperparameters
│   ├── experiment_v1.yaml    # Experiment variant 1
│   └── experiment_v2.yaml    # Experiment variant 2
│
├── data/                     # Data directory (gitignored)
│   ├── raw/                  # Original, immutable data
│   ├── processed/            # Cleaned, transformed data
│   └── README.md             # Data source documentation
│
├── src/                      # Source code
│   ├── __init__.py
│   ├── models/               # Model implementations
│   │   ├── __init__.py
│   │   ├── baseline.py       # Baseline model
│   │   └── proposed.py       # Proposed model
│   ├── data/                 # Data loading and processing
│   │   ├── __init__.py
│   │   ├── dataset.py        # Dataset class
│   │   └── transforms.py     # Data transformations
│   ├── training/             # Training logic
│   │   ├── __init__.py
│   │   ├── trainer.py        # Training loop
│   │   └── losses.py         # Custom loss functions
│   ├── evaluation/           # Evaluation metrics
│   │   ├── __init__.py
│   │   └── metrics.py        # Custom metrics
│   └── utils/                # Utilities
│       ├── __init__.py
│       ├── seed.py           # Random seed management
│       └── logging.py        # Logging configuration
│
├── scripts/                  # Executable scripts
│   ├── train.py              # Main training script
│   ├── evaluate.py           # Evaluation script
│   ├── preprocess.py         # Data preprocessing
│   └── visualize.py          # Result visualization
│
├── notebooks/                # Jupyter notebooks (exploration)
│   ├── 01_eda.ipynb
│   ├── 02_experiments.ipynb
│   └── 03_analysis.ipynb
│
├── tests/                    # Unit tests
│   ├── test_models.py
│   ├── test_data.py
│   └── test_training.py
│
├── outputs/                  # Experiment outputs (gitignored)
│   ├── checkpoints/          # Model checkpoints
│   ├── logs/                 # Training logs
│   └── figures/              # Generated figures
│
└── docs/                     # Additional documentation
    └── architecture.md
```

Generate this with:

```bash
mkdir -p {configs,data/{raw,processed},src/{models,data,training,evaluation,utils},scripts,notebooks,tests,outputs/{checkpoints,logs,figures},docs}
touch src/__init__.py src/models/__init__.py src/data/__init__.py src/training/__init__.py src/evaluation/__init__.py src/utils/__init__.py
```

#### Step 2.2: Generate Key Files

**Main Training Script Template:**

```python
#!/usr/bin/env python3
"""Main training script.

Usage:
    python scripts/train.py --config configs/default.yaml
    python scripts/train.py --config configs/experiment_v1.yaml --seed 42
"""

import argparse
import json
import logging
import os
import time

import numpy as np
import torch
from torch.utils.data import DataLoader

from src.utils.seed import set_seed
from src.models import build_model
from src.data.dataset import build_dataset
from src.training.trainer import Trainer
from src.evaluation.metrics import compute_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    import yaml
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to config YAML")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    args = parser.parse_args()

    config = load_config(args.config)
    set_seed(args.seed)

    output_dir = os.path.join(args.output_dir, f"run_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "config.json"), "w") as f:
        json.dump({**config, "seed": args.seed}, f, indent=2)

    logger.info(f"Config: {config}")
    logger.info(f"Output: {output_dir}")

    # Build components
    train_dataset = build_dataset(config["data"], split="train")
    val_dataset = build_dataset(config["data"], split="val")
    model = build_model(config["model"])

    train_loader = DataLoader(train_dataset, batch_size=config["training"]["batch_size"], shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=config["training"]["batch_size"])

    trainer = Trainer(model=model, config=config["training"], output_dir=output_dir)
    trainer.train(train_loader, val_loader)

    # Final evaluation
    metrics = compute_metrics(model, val_loader)
    logger.info(f"Final metrics: {metrics}")

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()
```

**Default Config Template (configs/default.yaml):**

```yaml
data:
  train_path: data/processed/train.csv
  val_path: data/processed/val.csv
  test_path: data/processed/test.csv
  num_workers: 4

model:
  type: proposed
  hidden_dim: 256
  num_layers: 3
  dropout: 0.1

training:
  epochs: 100
  batch_size: 32
  learning_rate: 0.001
  weight_decay: 0.0001
  optimizer: adam
  scheduler: cosine
  early_stopping_patience: 10
  gradient_clip: 1.0

evaluation:
  metrics: [accuracy, f1, precision, recall]
  save_predictions: true
```

**Seed Management (src/utils/seed.py):**

```python
"""Random seed management for reproducibility."""

import os
import random

import numpy as np


def set_seed(seed: int = 42) -> None:
    """Set all random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)

    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except ImportError:
        pass

    try:
        import tensorflow as tf
        tf.random.set_seed(seed)
    except ImportError:
        pass
```

### Phase 3: Code Quality for Research

#### Step 3.1: Testing Pyramid (6 Levels)

Go beyond shape tests. Use a testing pyramid from basic to advanced:

**Level 1 — Shape & Type** (minimum for any code):
```python
def test_output_shape():
    model = MyModel(input_dim=10, output_dim=3)
    assert model(torch.randn(32, 10)).shape == (32, 3)
```

**Level 2 — Determinism** (reproducibility):
```python
def test_reproducibility():
    set_seed(42); out1 = model(torch.randn(5, 10))
    set_seed(42); out2 = model(torch.randn(5, 10))
    torch.testing.assert_close(out1, out2)
```

**Level 3 — Numerical Correctness** (vs. known reference):
```python
def test_against_reference():
    x = torch.tensor([[1.0, 2.0]])
    expected = torch.tensor([[2.718, 7.389]])
    torch.testing.assert_close(my_exp(x), expected, atol=1e-3, rtol=1e-3)
```

**Level 4 — Gradient Flow** (for custom layers):
```python
def test_gradient_flow():
    model = MyModel(10, 3)
    x = torch.randn(4, 10, requires_grad=True)
    model(x).sum().backward()
    for name, p in model.named_parameters():
        assert p.grad is not None, f"No gradient for {name}"
        assert not torch.isnan(p.grad).any(), f"NaN gradient in {name}"
```

**Level 5 — Overfit Single Batch** (can the model learn at all?):
```python
def test_overfit_single_batch():
    model = MyModel(10, 3); opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    x, y = torch.randn(8, 10), torch.randint(0, 3, (8,))
    for _ in range(200):
        loss = F.cross_entropy(model(x), y); opt.zero_grad(); loss.backward(); opt.step()
    assert loss.item() < 0.01, "Cannot overfit single batch"
```

**Level 6 — Edge Cases** (robustness):
```python
def test_empty_input(): ...          # Empty batch
def test_single_element(): ...       # Batch size 1
def test_very_large_values(): ...    # Numerical stability
def test_all_same_values(): ...      # Degenerate input
```

#### Step 3.3: Three-Layer Documentation

Every module/class/function needs the right level of documentation:

**Layer 1 — WHY** (design decisions, in module/class docstrings):
```python
"""Feature extraction module.
We use ResNet over ViT because our domain (medical imaging) has limited
training data, and CNNs show better sample efficiency (see [Author2023]).
"""
```

**Layer 2 — WHAT** (API contract, in function docstrings):
```python
def compute_loss(predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    """Focal loss for class-imbalanced classification.
    
    Args:
        predictions: Logits, shape (B, C).
        targets: Labels, shape (B,), values in [0, C).
    Returns:
        Scalar loss tensor.
    Raises:
        ValueError: If shapes are incompatible.
    """
```

**Layer 3 — HOW** (usage examples, in README or docstrings):
```python
    """Example:
        >>> model = build_model(config)
        >>> loss = compute_loss(model(x), y)
        >>> loss.backward()
    """
```

**README template for research code repos**:
```markdown
# [Paper Title] — Official Implementation
> [One-sentence summary]

## Quick Start
pip install -r requirements.txt && python scripts/train.py --config configs/default.yaml

## Reproduce Paper Results
python scripts/train.py --config configs/paper_table1.yaml  # Table 1
python scripts/evaluate.py --config configs/ablation.yaml   # Figure 3
```

### Phase 3.3.5: Code as Narrative

Legendary code reads like a well-structured essay:

- **Top-down readability**: Public API first, private helpers below. Main logic before edge cases
- **Naming as documentation**: If you need a comment to explain a variable, the name is wrong. `x = data[:, :3]` → `spatial_coords = data[:, :3]`
- **40-line rule**: Functions > 40 lines do too much. Extract sub-functions — the function NAME becomes documentation
- **Headline test**: Read only method names of a class. Do they tell a story? `setup_model → setup_optimizer → train_epoch → evaluate → save_checkpoint` ✓

### Phase 3.5.5: Property-Based Testing

Beyond examples, test mathematical PROPERTIES that must hold for ALL inputs:

| Property | Test | Example |
|----------|------|---------|
| **Conservation** | `softmax(x).sum() ≈ 1` | Attention weights sum to 1 |
| **Bounds** | `0 ≤ sigmoid(x) ≤ 1` | Probabilities in valid range |
| **Symmetry** | `dist(a,b) == dist(b,a)` | Distance metrics |
| **Idempotence** | `norm(norm(x)) == norm(x)` | Normalization |
| **Equivariance** | `f(shift(x)) == shift(f(x))` | Translation equivariant conv |
| **Inverse** | `decode(encode(x)) ≈ x` | Autoencoder roundtrip |

```python
from hypothesis import given, strategies as st

@given(st.lists(st.floats(min_value=-100, max_value=100), min_size=1, max_size=100))
def test_softmax_conservation(values):
    x = torch.tensor(values)
    assert abs(F.softmax(x, dim=0).sum().item() - 1.0) < 1e-5
```

### Phase 3.7: Systematic Debugging Methodology

When code produces incorrect results, apply the scientific method — not random changes:

**5-Step Debugging Protocol**:
1. **Reproduce**: Minimal deterministic case (fixed seed, small data, single GPU)
2. **Hypothesize**: List 3-5 causes ranked by likelihood
3. **Isolate**: Binary search — disable half the pipeline, check if bug persists
4. **Verify**: Design a test that WOULD fail if the hypothesis is correct
5. **Fix & Regress**: Fix the bug, add a regression test

**ML Debugging Checklist**:
- [ ] Data loaded correctly? Print shapes, dtypes, value ranges, samples
- [ ] Labels aligned with inputs? Visualize input-label pairs
- [ ] Normalization correct? Mean≈0, std≈1 after transform
- [ ] Loss decreasing on single batch? If not, model/optimizer/loss is broken
- [ ] Gradients flowing? Check `param.grad` is not None/NaN after `.backward()`
- [ ] Learning rate appropriate? Too high → divergence, too low → no learning
- [ ] `model.eval()` + `torch.no_grad()` during evaluation?
- [ ] No data leakage? Check train/val/test splits are disjoint

### Phase 4: Benchmark Testing

#### Performance Comparison Template

```python
"""Benchmark comparison script."""

import time
import json
import numpy as np
from typing import Dict, List

def benchmark_model(model, test_loader, device="cpu") -> Dict:
    """Run benchmark evaluation."""
    model.eval()
    metrics = {"accuracy": [], "inference_time_ms": [], "memory_mb": []}

    for batch in test_loader:
        start = time.perf_counter()
        predictions = model.predict(batch)
        elapsed = (time.perf_counter() - start) * 1000

        metrics["inference_time_ms"].append(elapsed)
        metrics["accuracy"].append(compute_accuracy(predictions, batch.labels))

    return {
        "accuracy_mean": np.mean(metrics["accuracy"]),
        "accuracy_std": np.std(metrics["accuracy"]),
        "latency_mean_ms": np.mean(metrics["inference_time_ms"]),
        "latency_p95_ms": np.percentile(metrics["inference_time_ms"], 95),
        "throughput_samples_per_sec": len(test_loader.dataset) / (sum(metrics["inference_time_ms"]) / 1000),
    }


def compare_models(models: Dict, test_loader) -> str:
    """Compare multiple models and generate report."""
    results = {}
    for name, model in models.items():
        results[name] = benchmark_model(model, test_loader)

    # Generate comparison table
    header = "| Model | Accuracy | Latency (ms) | Throughput |"
    separator = "|-------|:--------:|:------------:|:----------:|"
    rows = []
    for name, r in results.items():
        rows.append(f"| {name} | {r['accuracy_mean']:.4f}±{r['accuracy_std']:.4f} | {r['latency_mean_ms']:.1f} | {r['throughput_samples_per_sec']:.0f}/s |")

    return "\n".join([header, separator] + rows)
```

### Phase 4.5: Performance-Aware Coding

**Complexity annotation**: State time/space complexity for every core algorithm:
```python
def compute_attention(Q, K, V):
    """Scaled dot-product attention. Time: O(n²·d), Space: O(n²)."""
    ...
```

**Vectorization rules**: NEVER loop over batch elements or sequence positions when a batched operation exists. Replace Python loops with NumPy/PyTorch vectorized ops.

**Memory optimization checklist**:
- `torch.no_grad()` during inference
- `del` large intermediates + `torch.cuda.empty_cache()`
- Gradient checkpointing for memory-constrained training
- `DataLoader(pin_memory=True, num_workers=4)` for GPU training

**Profile before optimizing**: Never guess — use `torch.profiler.profile()` or `cProfile` first.

### Phase 4.5.5: Algorithmic Complexity Derivation

Don't just state complexity — derive it, and ask "can the math reduce it?"

| Current → Target | Technique |
|:----------------:|-----------|
| O(n²) → O(n log n) | Divide and conquer / sorting |
| O(n²) → O(n) | Two pointers / sliding window |
| O(n²·d) → O(n·d) | Linear attention / kernel trick |
| Dense → Sparse O(nnz) | Exploit sparsity structure |

**"Can I avoid computing this?"**: Before optimizing, ask if you're computing information you never use. Common wins: full attention matrix when only top-k matters → sparse; all pairwise distances when only NN matters → KD-tree; recomputing loop-invariant values → hoist out.

### Phase 4.7: Code Review Checklist (Artifact Evaluation Level)

Use before submitting code as a paper artifact or sharing with collaborators:

**Correctness**:
- [ ] Code reproduces the reported numbers in the paper
- [ ] All hyperparameters consistent with the paper
- [ ] Random seeding comprehensive (Python, NumPy, PyTorch, CUDA)

**Readability**:
- [ ] Researcher in the field can understand in 30 minutes
- [ ] Variable names meaningful (not `x`, `tmp`, `data2`)
- [ ] README with setup + "quick start" one-command run
- [ ] Complex functions have docstrings (WHAT + WHY)

**Robustness**:
- [ ] Edge cases handled gracefully
- [ ] Input validation checks present
- [ ] Clear error messages, not cryptic tracebacks

**Reproducibility**:
- [ ] ALL dependencies pinned in requirements.txt
- [ ] Dockerfile or conda environment.yml provided
- [ ] Full training config saved alongside results
- [ ] One-command run after setup

**Performance**:
- [ ] No O(n²) where O(n) possible
- [ ] No unnecessary CPU↔GPU transfers in training loop
- [ ] DataLoader with multiple workers and pin_memory

## Advanced Methods

### ML Design Patterns

**Registry Pattern** (extensible model/loss/dataset selection):
```python
REGISTRY = {}
def register(name):
    def decorator(cls):
        REGISTRY[name] = cls
        return cls
    return decorator

@register("resnet18")
class ResNet18(nn.Module): ...

def build_model(config):
    return REGISTRY[config.model.type](**config.model.params)
```

**Callback System** (extensible training loop):
```python
class Callback:
    def on_epoch_start(self, epoch, trainer): pass
    def on_epoch_end(self, epoch, metrics, trainer): pass

class EarlyStoppingCallback(Callback):
    def __init__(self, patience=10, metric="val_loss"):
        self.patience, self.metric = patience, metric
        self.best, self.counter = float("inf"), 0
    
    def on_epoch_end(self, epoch, metrics, trainer):
        if metrics[self.metric] < self.best:
            self.best = metrics[self.metric]; self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience: trainer.should_stop = True
```

### GPU & Distributed Training

**Mixed Precision** (2x speedup, 50% memory reduction):
```python
scaler = torch.cuda.amp.GradScaler()
for batch in dataloader:
    with torch.cuda.amp.autocast():
        loss = criterion(model(batch), targets)
    scaler.scale(loss).backward()
    scaler.step(optimizer); scaler.update(); optimizer.zero_grad()
```

**Distributed Data Parallel** (multi-GPU):
```python
dist.init_process_group("nccl")
model = DDP(model.to(local_rank), device_ids=[local_rank])
dataloader = DataLoader(dataset, sampler=DistributedSampler(dataset))
```

**Gradient Accumulation** (simulate larger batches):
```python
for i, batch in enumerate(dataloader):
    (model(batch) / accum_steps).backward()
    if (i + 1) % accum_steps == 0:
        optimizer.step(); optimizer.zero_grad()
```

## Integration with Other Skills

- **literature-review**: Find the paper → use this skill to reproduce it
- **statistical-analysis**: Analyze experiment results statistically
- **experiment-tracking**: Track experiment runs and configurations
- **dataset-search**: Find datasets to test the implementation
- **academic-writing**: Generate method/experiment sections from code
- **academic-ppt**: Create presentation slides showing results

## Best Practices

1. **Always cite the paper** in code comments and docstrings
2. **Map equations to code** with explicit references (Eq. 1, Section 3.2)
3. **Use configuration files** instead of hardcoded hyperparameters
4. **Set random seeds** at every level (Python, NumPy, PyTorch, CUDA)
5. **Log everything** — parameters, metrics, system info, git hash
6. **Write tests** even for research code — at minimum, shape tests and determinism tests
7. **Version control** — commit early, commit often, use meaningful messages
8. **Document** assumptions, limitations, and deviations from the paper

## Notes

- When reproducing a paper, focus on matching the core algorithm first, then optimize
- Expect slight numerical differences due to floating-point precision, library versions, and undocumented details
- If a paper doesn't provide implementation details, check their GitHub repo or supplementary materials
- Use `web_search` to find existing implementations before writing from scratch
- Always compare your reproduction against reported numbers in the paper
