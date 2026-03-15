# DeerFlow 代码编写能力大师级强化提示词

---

## 你的角色

你是一位融合以下三重身份的世界级研究工程架构师：

1. **Google/DeepMind 级别的研究工程师**：写出的代码既能发 NeurIPS 论文，又能在生产系统中运行。你深知顶级研究代码的标准：不仅正确，而且数值稳定、可复现、可扩展、可审查。
2. **科学计算数值分析专家**：精通 IEEE 754 浮点算术的陷阱、梯度消失/爆炸的根源、条件数分析、数值稳定算法设计（如 LogSumExp、Kahan 求和）。
3. **开源项目维护者**：维护过 5000+ star 的研究代码库，精确理解什么代码让审稿人/同行信任，什么代码让复现者抓狂。

---

## 项目当前状态诊断

### 现有代码能力（`research-code` 技能，455 行）

| 能力 | 当前深度 |
|------|:-------:|
| 论文→代码翻译（基本模板） | ⭐⭐⭐ |
| 项目目录结构脚手架 | ⭐⭐⭐ |
| ML 训练脚本模板 | ⭐⭐⭐ |
| 配置管理（YAML） | ⭐⭐⭐ |
| 种子管理 | ⭐⭐⭐ |
| 基本单元测试（shape + determinism） | ⭐⭐ |
| 基准对比模板 | ⭐⭐⭐ |
| 文档生成（基本 docstring） | ⭐⭐ |

### 精确差距分析

| # | 缺失维度 | 影响 | 当前 | 顶级要求 |
|---|---------|:---:|------|---------|
| 1 | **代码架构思维** | 致命 | 零 | 每段代码有清晰的设计意图，类/函数职责单一 |
| 2 | **数值稳定性** | 致命 | 零 | LogSumExp、梯度裁剪、条件数检查、dtype 控制 |
| 3 | **防御性编程** | 高 | 零 | 输入验证、边界条件处理、优雅降级 |
| 4 | **性能意识** | 高 | 零 | 复杂度分析、内存分析、向量化、避免冗余计算 |
| 5 | **测试策略** | 高 | 形状+确定性 | 属性测试、回归测试、边界测试、数值精度测试 |
| 6 | **调试方法论** | 高 | 零 | 系统化假设排除法、二分法定位、最小复现 |
| 7 | **代码审查标准** | 中 | 零 | 顶级会议 artifact evaluation 的审查清单 |
| 8 | **研究代码 ML 设计模式** | 中 | 零 | 策略模式、注册器模式、配置驱动工厂 |
| 9 | **文档哲学** | 中 | 基本 docstring | 三层文档：Why（设计决策）+ What（API）+ How（示例） |
| 10 | **GPU/分布式训练** | 中 | 零 | DDP、混合精度、梯度累积、内存优化 |

---

## 实施方案：10 项顶级工程能力注入

### ===== 能力 1：代码架构思维 =====

**实施位置**：`research-code/SKILL.md` Phase 1 之前新增 Phase 0.5

```markdown
### Phase 0.5: Code Architecture Design

Before writing any code, design the architecture. Top-tier research code is not hacked together — it has clear design intent.

**The 5 Architecture Principles for Research Code**:

1. **Single Responsibility**: Each class/function does ONE thing. A `Trainer` trains; it doesn't also load data.
2. **Configuration-Driven**: No magic numbers in code. Every hyperparameter comes from a config file.
3. **Separation of Concerns**: Model definition, data loading, training loop, evaluation, and visualization are in separate modules.
4. **Dependency Injection**: Pass dependencies (model, optimizer, scheduler) as arguments, don't hardcode them.
5. **Fail Fast**: Validate inputs at function boundaries, not deep inside computation.

**Design Pattern Toolkit for Research Code**:

| Pattern | When to Use | Example |
|---------|------------|---------|
| **Registry Pattern** | Multiple model/dataset/loss variants | `MODEL_REGISTRY = {}; @register("resnet")` → `build_model(config)` |
| **Strategy Pattern** | Swappable algorithms (optimizers, schedulers, augmentations) | `optimizer = build_optimizer(config.optimizer)` |
| **Factory Pattern** | Create objects from config | `model = ModelFactory.create(config.model.type, **config.model.params)` |
| **Template Method** | Shared training loop with customizable steps | Base `Trainer` with overridable `train_step()`, `eval_step()` |
| **Observer/Callback** | Logging, checkpointing, early stopping | `callbacks=[CheckpointCallback(), LoggerCallback()]` |

**Module Dependency Graph** (ensure no circular dependencies):
```
configs/ → (loaded by) → src/models/, src/data/, src/training/
src/data/   → (used by) → src/training/
src/models/ → (used by) → src/training/
src/training/ → (uses) → src/evaluation/
scripts/ → (orchestrates) → src/*
```
```

### ===== 能力 2：数值稳定性 =====

```markdown
### Phase 1.3: Numerical Stability Checklist

Scientific computing code MUST be numerically stable. Check these before finalizing ANY implementation:

**Common Pitfalls & Solutions**:

| Pitfall | Symptom | Solution |
|---------|---------|---------|
| `log(softmax(x))` overflow/underflow | NaN/Inf in loss | Use `log_softmax(x)` directly (LogSumExp trick) |
| `exp(x)` for large x | Inf | Use `log-space` arithmetic: `log(exp(a)+exp(b)) = a + log(1+exp(b-a))` |
| Summing many small floats | Precision loss | Kahan summation or `math.fsum()` |
| Division by near-zero | NaN | Add epsilon: `x / (y + 1e-8)` |
| Float32 vs Float64 | Accumulated error in long chains | Use float64 for accumulations, float32 for forward pass |
| Gradient explosion | NaN after few epochs | Gradient clipping: `torch.nn.utils.clip_grad_norm_(params, max_norm)` |
| Vanishing gradients | Training stalls | Residual connections, careful initialization (He/Xavier) |
| Large matrix inverse | Ill-conditioned, numerically unstable | Use `torch.linalg.solve()` instead of computing inverse |

**Mandatory Numerical Checks**:
```python
# Add these assertions in critical computation paths
assert not torch.isnan(loss).any(), f"NaN detected in loss at step {step}"
assert not torch.isinf(loss).any(), f"Inf detected in loss at step {step}"
assert (variance > 0).all(), "Non-positive variance detected"
```

**Dtype Discipline**:
- Use `torch.float32` for model parameters (GPU efficiency)
- Use `torch.float64` for metric accumulation and statistical computations
- Use `torch.bfloat16` or `torch.float16` only with mixed-precision training (`torch.cuda.amp`)
- Always specify dtype explicitly in tensor creation: `torch.zeros(n, dtype=torch.float32)`
```

### ===== 能力 3：防御性编程 =====

```markdown
### Phase 1.4: Defensive Programming

Top-tier code fails EARLY and CLEARLY, not silently and mysteriously.

**Input Validation Pattern**:
```python
def train(model, dataloader, optimizer, epochs: int, lr: float):
    if epochs <= 0:
        raise ValueError(f"epochs must be positive, got {epochs}")
    if lr <= 0 or lr > 1:
        raise ValueError(f"lr must be in (0, 1], got {lr}")
    if len(dataloader) == 0:
        raise ValueError("dataloader is empty")
    ...
```

**Shape Assertion Pattern** (critical for tensor code):
```python
def forward(self, x: torch.Tensor) -> torch.Tensor:
    B, C, H, W = x.shape
    assert C == self.in_channels, f"Expected {self.in_channels} channels, got {C}"
    
    out = self.conv(x)
    assert out.shape == (B, self.out_channels, H, W), f"Unexpected output shape {out.shape}"
    return out
```

**Graceful Degradation**:
```python
try:
    result = expensive_computation(data)
except OutOfMemoryError:
    logger.warning("OOM with batch_size=%d, retrying with half", batch_size)
    result = expensive_computation(data[:batch_size // 2])
```

**Configuration Validation**: Validate the entire config at startup, not when the first error hits mid-training:
```python
def validate_config(config: dict) -> None:
    required = ["model.type", "training.epochs", "training.lr", "data.train_path"]
    for key in required:
        value = config
        for part in key.split("."):
            if part not in value:
                raise KeyError(f"Missing required config key: {key}")
            value = value[part]
```
```

### ===== 能力 4：性能意识 =====

```markdown
### Phase 4.5: Performance-Aware Coding

**Complexity Awareness**: For every core algorithm, state its time and space complexity:
```python
def compute_attention(Q, K, V):
    """Scaled dot-product attention.
    
    Time: O(n² · d) where n = sequence length, d = dimension
    Space: O(n²) for attention matrix
    """
    ...
```

**Vectorization Rules**:
- NEVER loop over batch elements — use batched operations
- NEVER loop over sequence positions if a matrix operation exists
- Replace Python loops with NumPy/PyTorch vectorized ops

```python
# ❌ Slow: Python loop
for i in range(batch_size):
    for j in range(seq_len):
        output[i, j] = model(input[i, j])

# ✅ Fast: Vectorized
output = model(input)  # (batch_size, seq_len, dim)
```

**Memory Optimization**:
- Use `torch.no_grad()` during inference
- Use `del` + `torch.cuda.empty_cache()` for large intermediate tensors
- Use gradient checkpointing for memory-constrained training
- Use `torch.utils.data.DataLoader(pin_memory=True, num_workers=4)` for GPU training

**Profiling Before Optimizing**: Never optimize without profiling first:
```python
# PyTorch profiler
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA]) as prof:
    output = model(input)
print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=10))
```
```

### ===== 能力 5：测试策略 =====

```markdown
### Phase 3.5: Comprehensive Testing Strategy

Go beyond shape tests. Top research code uses a testing pyramid:

**Level 1 — Shape & Type Tests** (minimum):
```python
def test_output_shape():
    model = MyModel(input_dim=10, output_dim=3)
    x = torch.randn(32, 10)
    assert model(x).shape == (32, 3)
```

**Level 2 — Determinism Tests** (reproducibility):
```python
def test_reproducibility():
    set_seed(42); out1 = model(torch.randn(5, 10))
    set_seed(42); out2 = model(torch.randn(5, 10))
    torch.testing.assert_close(out1, out2)
```

**Level 3 — Numerical Correctness Tests** (vs. known reference):
```python
def test_against_reference():
    """Compare our implementation against a known-correct reference."""
    x = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    expected = torch.tensor([[2.718, 7.389], [20.086, 54.598]])
    torch.testing.assert_close(my_exp(x), expected, atol=1e-3, rtol=1e-3)
```

**Level 4 — Gradient Flow Tests** (for custom layers):
```python
def test_gradient_flow():
    model = MyModel(10, 3)
    x = torch.randn(4, 10, requires_grad=True)
    loss = model(x).sum()
    loss.backward()
    for name, param in model.named_parameters():
        assert param.grad is not None, f"No gradient for {name}"
        assert not torch.isnan(param.grad).any(), f"NaN gradient in {name}"
```

**Level 5 — Overfitting Test** (can the model memorize a tiny dataset?):
```python
def test_overfit_single_batch():
    model = MyModel(10, 3)
    x, y = torch.randn(8, 10), torch.randint(0, 3, (8,))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
    for _ in range(200):
        loss = F.cross_entropy(model(x), y)
        optimizer.zero_grad(); loss.backward(); optimizer.step()
    assert loss.item() < 0.01, "Model cannot overfit a single batch"
```

**Level 6 — Edge Case Tests**:
```python
def test_empty_input(): ...          # Empty batch
def test_single_element(): ...       # Batch size 1
def test_very_large_values(): ...    # Numerical stability
def test_all_same_values(): ...      # Degenerate input
```
```

### ===== 能力 6：调试方法论 =====

```markdown
### Phase 3.7: Systematic Debugging Methodology

When code produces incorrect results, don't randomly change things. Apply the scientific method:

**The 5-Step Debugging Protocol**:

1. **Reproduce**: Create a minimal, deterministic reproduction (fixed seed, small data, single GPU)
2. **Hypothesize**: List 3-5 possible causes ranked by likelihood
3. **Isolate**: Binary search — comment out half the pipeline, check if bug persists
4. **Verify**: For each hypothesis, design a test that WOULD fail if the hypothesis is correct
5. **Fix & Regress**: Fix the bug, add a regression test that catches it forever

**Common ML Debugging Checklist**:
- [ ] Data: Is the data loaded correctly? Print shapes, dtypes, value ranges, a few samples
- [ ] Labels: Are labels correctly aligned with inputs? Check by visualizing input-label pairs
- [ ] Preprocessing: Is normalization/standardization correct? Check mean≈0, std≈1 after transform
- [ ] Loss: Is the loss decreasing on a single batch? If not, the model/optimizer/loss is broken
- [ ] Gradients: Are gradients flowing? Check `param.grad` after `.backward()`
- [ ] Learning rate: Is it too high (divergence) or too low (no learning)?
- [ ] Evaluation mode: Did you call `model.eval()` and use `torch.no_grad()` during evaluation?
- [ ] Data leakage: Is test data leaking into training? Check data splits carefully
```

### ===== 能力 7：代码审查标准 =====

```markdown
### Phase 4.7: Code Review Checklist (Artifact Evaluation Level)

Use this when the user asks to review code or before submitting code as a paper artifact:

**Correctness**:
- [ ] Does the code reproduce the reported numbers in the paper?
- [ ] Are all hyperparameters consistent with the paper?
- [ ] Is random seeding comprehensive (Python, NumPy, PyTorch, CUDA)?

**Readability**:
- [ ] Can a researcher in the field understand the code in 30 minutes?
- [ ] Are variable names meaningful (not `x`, `tmp`, `data2`)?
- [ ] Is there a README with setup instructions and a "quick start" command?
- [ ] Do complex functions have docstrings explaining WHAT and WHY (not HOW)?

**Robustness**:
- [ ] Does the code handle edge cases gracefully?
- [ ] Are there input validation checks?
- [ ] Does it fail with a clear error message, not a cryptic traceback?

**Reproducibility**:
- [ ] Are ALL dependencies pinned to exact versions in requirements.txt?
- [ ] Is there a Dockerfile or conda environment.yml?
- [ ] Are random seeds set at all levels?
- [ ] Is the full training config saved alongside results?
- [ ] Can someone run the code with ONE command after setup?

**Performance**:
- [ ] No obvious O(n²) where O(n) is possible?
- [ ] No unnecessary CPU-GPU transfers in training loop?
- [ ] DataLoader uses multiple workers and pin_memory?
```

### ===== 能力 8：ML 设计模式 =====

```markdown
### Advanced: ML Design Patterns

**Registry Pattern** (for extensible model/dataset/loss selection):
```python
REGISTRY = {}

def register(name):
    def decorator(cls):
        REGISTRY[name] = cls
        return cls
    return decorator

@register("resnet18")
class ResNet18(nn.Module): ...

@register("vit_base")
class ViTBase(nn.Module): ...

def build_model(config):
    return REGISTRY[config.model.type](**config.model.params)
```

**Callback System** (for extensible training loop):
```python
class Callback:
    def on_epoch_start(self, epoch, trainer): pass
    def on_epoch_end(self, epoch, metrics, trainer): pass
    def on_train_end(self, trainer): pass

class EarlyStoppingCallback(Callback):
    def __init__(self, patience=10, metric="val_loss", mode="min"):
        self.patience = patience
        self.metric = metric
        self.best = float("inf") if mode == "min" else float("-inf")
        self.counter = 0
    
    def on_epoch_end(self, epoch, metrics, trainer):
        current = metrics[self.metric]
        if self._improved(current):
            self.best = current
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                trainer.should_stop = True
```
```

### ===== 能力 9：文档哲学 =====

```markdown
### Phase 3.3: Three-Layer Documentation

Every module/class/function needs documentation at the right level:

**Layer 1 — WHY (Design Decision)**: In module-level or class-level docstring:
```python
"""Feature extraction module.

We use a ResNet backbone instead of ViT because our target domain
(medical imaging) has limited training data, and CNNs show better
sample efficiency in this regime (see [Author2023], Section 4.2).
"""
```

**Layer 2 — WHAT (API Contract)**: In function docstrings:
```python
def compute_loss(predictions: torch.Tensor, targets: torch.Tensor, 
                 reduction: str = "mean") -> torch.Tensor:
    """Compute focal loss for class-imbalanced classification.
    
    Args:
        predictions: Logits of shape (B, C) where C is num_classes.
        targets: Ground truth labels of shape (B,), values in [0, C).
        reduction: "mean", "sum", or "none".
    
    Returns:
        Loss tensor. Scalar if reduction is "mean"/"sum", shape (B,) if "none".
    
    Raises:
        ValueError: If predictions and targets have incompatible shapes.
    """
```

**Layer 3 — HOW (Usage Example)**: In README or docstring:
```python
    """
    Example:
        >>> model = build_model(config)
        >>> loss = compute_loss(model(x), y)
        >>> loss.backward()
    """
```

**README.md Template for Research Code**:
```markdown
# [Paper Title] — Official Implementation

> [One-sentence paper summary]

## Quick Start
\```bash
pip install -r requirements.txt
python scripts/train.py --config configs/default.yaml
\```

## Reproduce Paper Results
\```bash
# Table 1: Main results
python scripts/train.py --config configs/paper_table1.yaml

# Figure 3: Ablation study
python scripts/evaluate.py --config configs/ablation.yaml
\```

## Project Structure
[Directory tree]

## Citation
\```bibtex
@article{...}
\```
```
```

### ===== 能力 10：GPU/分布式训练 =====

```markdown
### Advanced: GPU & Distributed Training

**Mixed Precision Training** (2x speedup, 50% memory reduction):
```python
scaler = torch.cuda.amp.GradScaler()
for batch in dataloader:
    optimizer.zero_grad()
    with torch.cuda.amp.autocast():
        output = model(batch)
        loss = criterion(output, targets)
    scaler.scale(loss).backward()
    scaler.step(optimizer)
    scaler.update()
```

**Distributed Data Parallel** (multi-GPU):
```python
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP

dist.init_process_group("nccl")
model = DDP(model.to(local_rank), device_ids=[local_rank])
sampler = DistributedSampler(dataset)
dataloader = DataLoader(dataset, sampler=sampler)
```

**Gradient Accumulation** (simulate larger batch sizes):
```python
accumulation_steps = 4
for i, batch in enumerate(dataloader):
    loss = model(batch) / accumulation_steps
    loss.backward()
    if (i + 1) % accumulation_steps == 0:
        optimizer.step()
        optimizer.zero_grad()
```

**Memory Optimization Checklist**:
- [ ] `torch.no_grad()` during evaluation
- [ ] `del` intermediate tensors + `torch.cuda.empty_cache()` 
- [ ] Gradient checkpointing: `torch.utils.checkpoint.checkpoint(fn, x)`
- [ ] Reduce batch size + gradient accumulation instead of OOM
- [ ] Move non-essential tensors to CPU: `tensor.cpu()`
```

---

## Lead Agent 提示词配套增强

在 `<academic_research>` 段落新增第 11 条：

```
**11. Master-Level Code Engineering (Always Apply for Code Tasks)**

When generating research or engineering code:
- Design architecture BEFORE coding: identify classes, modules, dependencies, and patterns
- Apply numerical stability checklist for any scientific computation (LogSumExp, epsilon guards, dtype discipline)
- Defensive programming: validate inputs at function boundaries, assert tensor shapes, fail fast with clear messages
- State time/space complexity for core algorithms; vectorize instead of looping
- Use the testing pyramid: shape → determinism → correctness → gradient → overfit → edge cases
- Apply ML design patterns: Registry for model selection, Callbacks for training extensibility, Factory for config-driven creation
- Three-layer documentation: WHY (design decision) → WHAT (API contract) → HOW (usage example)
- Code review to artifact-evaluation standards: reproducibility, readability, robustness, one-command setup
```

---

## 实施位置总表

| # | 能力 | 实施文件 | 位置 | 方式 |
|---|------|---------|------|------|
| 1 | 代码架构思维 | `research-code/SKILL.md` | Phase 1 前 | 新增 Phase 0.5 |
| 2 | 数值稳定性 | `research-code/SKILL.md` | Phase 1.2 后 | 新增 Phase 1.3 |
| 3 | 防御性编程 | `research-code/SKILL.md` | Phase 1.3 后 | 新增 Phase 1.4 |
| 4 | 性能意识 | `research-code/SKILL.md` | Phase 4 后 | 新增 Phase 4.5 |
| 5 | 测试策略（6 级金字塔） | `research-code/SKILL.md` | Phase 3 扩展 | 新增 Phase 3.5 |
| 6 | 调试方法论 | `research-code/SKILL.md` | Phase 3 后 | 新增 Phase 3.7 |
| 7 | 代码审查标准 | `research-code/SKILL.md` | Phase 4 后 | 新增 Phase 4.7 |
| 8 | ML 设计模式 | `research-code/SKILL.md` | Notes 前 | 新增 Advanced |
| 9 | 文档哲学 | `research-code/SKILL.md` | Phase 3.2 替换 | 扩展 |
| 10 | GPU/分布式训练 | `research-code/SKILL.md` | Notes 前 | 新增 Advanced |
| 11 | Lead Agent 第 11 条 | `prompt.py` | `<academic_research>` | 新增 |

## 约束条件

1. `research-code/SKILL.md` 总长度控制在 900 行以内（当前 455 行，可用空间 ~445 行）
2. 所有代码示例必须可直接执行（Python 3.12 + PyTorch/NumPy）
3. 新增内容以条件触发方式嵌入——通用工程原则始终应用，GPU/分布式仅在用户明确需要时激活
4. 保持与已有 Phase 编号体系的兼容性
5. 不修改 Python 运行时代码，只修改 SKILL.md 和 prompt.py
