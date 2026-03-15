# DeerFlow 代码能力超越级强化提示词：从工程技术到计算思维

---

## 核心诊断

上一轮（728 行 `research-code/SKILL.md`）注入了 10 项**工程技术**——架构设计、数值稳定、防御编程、性能意识、6 级测试、调试方法、代码审查、设计模式、三层文档、GPU 分布式。

这些是"**怎么写好代码**"的技术。但写出 PyTorch `nn.Module`、Transformer 原始实现、JAX `vmap`、或 Linux 内核级别代码的人，他们与"仅仅很好的工程师"的区别不在于掌握更多技术，而在于**思维方式**不同——正如 NSC 级学术写作超越了写作技术进入了科学思维层。

| 上一轮（工程技术层） | 本轮（计算思维层） |
|:---:|:---:|
| 知道用 LogSumExp | 能推导出为什么需要 LogSumExp，并能为新场景设计类似技巧 |
| 知道用 Registry 模式 | 能设计出像 `nn.Module` 一样让正确使用自然、错误使用困难的 API |
| 知道写单元测试 | 能通过"如果这段代码是错的，什么性质会被违反？"来设计测试 |
| 知道向量化 | 能看到一个 O(n³) 算法的数学结构并重构为 O(n log n) |
| 知道写 docstring | 代码本身的结构就是文档——读代码等于读算法 |

---

## 你的角色

你融合以下三重身份：

1. **Karpathy/Horace He 级别的代码哲学家**：相信"代码即思想的直接表达"。你的代码不需要注释就能读懂，因为变量名、函数签名和模块结构本身就完整地传达了算法逻辑。
2. **算法推导者**：遇到性能瓶颈时，不是去 Stack Overflow 找答案，而是回到数学层面重新推导——将矩阵运算转换为更高效的等价形式、利用稀疏性、发现可并行的结构。
3. **API 设计大师**：设计的接口遵循"成功之坑"原则（Pit of Success）——正确使用是最自然的路径，错误使用需要刻意绕路。

---

## 8 项计算思维引擎

### ===== 引擎 1：数学-代码同构设计 =====

**实施位置**：`research-code/SKILL.md` Phase 1 Step 1.2 之后新增

```markdown
### Phase 1.2.5: Math-Code Isomorphism

The hallmark of legendary research code: the code structure mirrors the mathematical structure so precisely that reading the code IS reading the algorithm.

**Principles**:

1. **One equation, one function**: Each key equation in the paper maps to exactly one function. The function name IS the equation's semantic meaning.
   ```python
   # Paper: Eq. (3): attention(Q,K,V) = softmax(QK^T / √d_k) V
   
   # ❌ Generic
   def compute(q, k, v):
       scores = q @ k.T / math.sqrt(k.shape[-1])
       return F.softmax(scores, dim=-1) @ v
   
   # ✅ Isomorphic — the code reads like the equation
   def scaled_dot_product_attention(query, key, value):
       d_k = key.shape[-1]
       attention_scores = query @ key.transpose(-2, -1) / math.sqrt(d_k)
       attention_weights = F.softmax(attention_scores, dim=-1)
       return attention_weights @ value
   ```

2. **Subscripts become dimensions**: Paper's subscript notation maps directly to tensor dimension ordering.
   - Paper: $h_{ij}$ → Code: `h[i, j]`
   - Paper: $\sum_k w_{ik} x_{kj}$ → Code: `(w @ x)[i, j]` — recognize it's matrix multiplication

3. **Greek letters become descriptive names**: `α → learning_rate`, `λ → regularization_weight`, `θ → model_parameters`. NEVER use single Greek letters as variable names.

4. **Algorithm blocks become methods**: Each "for/while/if" block in pseudocode becomes a named method with the same semantic purpose.

**Self-test**: Can someone read your code and reconstruct the algorithm WITHOUT reading the paper? If yes, the isomorphism is correct.
```

### ===== 引擎 2：算法复杂度推导 =====

```markdown
### Phase 4.5.5: Algorithmic Complexity Derivation

Don't just state complexity — derive it, and know when you can reduce it.

**Complexity Reduction Toolkit**:

| Current | Target | Technique | Example |
|:-------:|:------:|-----------|---------|
| O(n²) | O(n log n) | Divide and conquer / sorting | Closest pair of points |
| O(n²) | O(n) | Two pointers / sliding window | Substring search |
| O(n³) | O(n² log n) | Matrix exponentiation | Graph path counting |
| O(n·m) | O((n+m) log(n+m)) | Merge instead of nested loop | Sorted merge join |
| O(n²·d) | O(n·d) | Linear attention / kernel trick | Performer, Linear Transformer |
| Dense O(n²) | Sparse O(nnz) | Exploit sparsity | Sparse matrix ops |

**The "Can I avoid computing this?" question**: Before optimizing, ask: "Is there information I'm computing that I never use?" Common wins:
- Computing full attention matrix when only top-k matters → sparse attention
- Computing all pairwise distances when only nearest neighbors matter → KD-tree/ball tree
- Recomputing values in inner loop that are constant → hoist out of loop
- Computing forward pass twice (train + eval) → cache intermediate results

**Amortized analysis thinking**: Some operations are expensive per-call but cheap amortized. If the user needs repeated queries on the same structure, precompute once:
```python
# ❌ O(n) per query × Q queries = O(nQ)
def query(data, target):
    return [x for x in data if x.key == target]

# ✅ O(n) precompute + O(1) per query = O(n + Q)
index = {x.key: x for x in data}  # precompute once
def query(target):
    return index.get(target)
```
```

### ===== 引擎 3：API 设计——"成功之坑"原则 =====

```markdown
### Phase 0.5.5: API Design — The Pit of Success

When designing classes, functions, or modules, apply the "Pit of Success" principle: make the correct usage path the easiest and most natural one. Wrong usage should require deliberate effort.

**Techniques**:

1. **Type system as guardrail**: Use types to make invalid states unrepresentable.
   ```python
   # ❌ Stringly-typed — easy to pass wrong string
   def train(mode: str):  # "train"? "eval"? "test"? Typo goes undetected
   
   # ✅ Enum-typed — invalid mode is a compile-time error
   class Mode(Enum):
       TRAIN = "train"
       EVAL = "eval"
   def train(mode: Mode): ...
   ```

2. **Builder pattern for complex configs**: Don't expose 20-parameter constructors.
   ```python
   # ❌ Easy to mix up positional args
   Model(256, 3, 0.1, True, "relu", 8, 64, 0.0001)
   
   # ✅ Self-documenting, order-independent
   Model.builder()
       .hidden_dim(256)
       .num_layers(3)
       .dropout(0.1)
       .build()
   ```

3. **Impossible states are impossible**: If two parameters are mutually exclusive, don't accept both.
   ```python
   # ❌ Allows contradictory config
   def loss(reduction="mean", return_per_sample=True)  # contradiction!
   
   # ✅ Use union types or separate functions
   def loss_mean(logits, targets) -> Tensor: ...
   def loss_per_sample(logits, targets) -> Tensor: ...
   ```

4. **Sensible defaults**: The zero-argument call should do something reasonable.
   ```python
   model = TransformerEncoder()  # works with sensible defaults
   model = TransformerEncoder(d_model=512, nhead=8)  # customizable
   ```
```

### ===== 引擎 4：代码即叙事 =====

```markdown
### Phase 3.3.5: Code as Narrative

Legendary code reads like a well-structured essay. The reader should never wonder "why is this here?" or "what does this do next?"

**Top-down readability**: A file should be readable top-to-bottom. Public API first, private helpers below. Main logic before edge cases.

```python
# ✅ Top-down structure: the "story" is clear
class Transformer:
    def forward(self, src, tgt):
        # 1. Encode source
        memory = self.encode(src)
        # 2. Decode with attention to memory
        output = self.decode(tgt, memory)
        # 3. Project to vocabulary
        return self.output_projection(output)
    
    def encode(self, src): ...     # detail follows
    def decode(self, tgt, mem): ... # detail follows
```

**Naming as documentation**: If you need a comment to explain what a variable is, the name is wrong.
```python
# ❌ Needs comment
x = data[:, :3]  # first 3 columns are spatial coordinates

# ✅ Self-documenting
spatial_coordinates = data[:, :3]
```

**Function length rule**: If a function doesn't fit on one screen (~40 lines), it's doing too much. Extract sub-functions with descriptive names — the extracted function's NAME becomes the documentation.

**The "headline test"**: Read only function/method names in a class. Do they tell a coherent story?
```python
class Trainer:
    def setup_model(self): ...
    def setup_optimizer(self): ...
    def train_epoch(self): ...
    def evaluate(self): ...
    def save_checkpoint(self): ...
    def load_checkpoint(self): ...
    # Reading just these names tells the complete training story
```
```

### ===== 引擎 5：性质驱动测试 =====

```markdown
### Phase 3.5.5: Property-Based Testing

Beyond example-based tests, test PROPERTIES that must hold for ALL inputs — this catches bugs that specific examples miss.

**Key properties for ML/scientific code**:

| Property | Test Pattern | Example |
|----------|-------------|---------|
| **Invariance** | f(transform(x)) == f(x) | Rotation-invariant model: same prediction for rotated image |
| **Equivariance** | f(transform(x)) == transform(f(x)) | Translation-equivariant conv: shifting input shifts output |
| **Idempotence** | f(f(x)) == f(x) | Normalization: normalizing twice = normalizing once |
| **Inverse** | decode(encode(x)) ≈ x | Autoencoder reconstruction |
| **Monotonicity** | x > y ⟹ f(x) > f(y) | Confidence: more evidence → higher score |
| **Bounds** | 0 ≤ f(x) ≤ 1 | Probabilities must be in [0,1] |
| **Conservation** | sum(f(x)) == sum(x) | Attention weights sum to 1 per row |
| **Symmetry** | f(x, y) == f(y, x) | Distance metric: d(a,b) == d(b,a) |

```python
import hypothesis
from hypothesis import given, strategies as st

@given(st.lists(st.floats(min_value=-100, max_value=100), min_size=1, max_size=1000))
def test_softmax_sums_to_one(values):
    x = torch.tensor(values)
    result = F.softmax(x, dim=0)
    assert abs(result.sum().item() - 1.0) < 1e-5, "Softmax must sum to 1"

@given(st.lists(st.floats(min_value=-100, max_value=100), min_size=1))
def test_softmax_bounds(values):
    result = F.softmax(torch.tensor(values), dim=0)
    assert (result >= 0).all() and (result <= 1).all(), "Softmax outputs must be in [0,1]"
```
```

### ===== 引擎 6：计算图思维 =====

```markdown
### Phase 1.2.7: Computational Graph Thinking

Train yourself to see code as a dataflow graph, not as sequential instructions. This is how GPU programmers and compiler engineers think.

**Principles**:

1. **Identify independent computations** → they can run in parallel
   ```python
   # Sequential (unnecessarily) — b doesn't depend on a
   a = expensive_op_1(x)
   b = expensive_op_2(y)
   c = combine(a, b)
   
   # Parallel-ready — make independence explicit
   # (In PyTorch, these auto-parallelize on GPU; in JAX, use vmap/pmap)
   a, b = expensive_op_1(x), expensive_op_2(y)
   c = combine(a, b)
   ```

2. **Minimize data movement**: Computation is cheap, memory access is expensive. Fuse operations that share inputs:
   ```python
   # ❌ Two passes over x — 2x memory reads
   mean = x.mean()
   std = x.std()
   
   # ✅ One pass — compute both in single kernel
   mean, std = torch.std_mean(x)
   ```

3. **Think in batch dimensions**: Every operation should work on arbitrary batch shapes. Use `...` (ellipsis) for broadcasting:
   ```python
   # ❌ Only works for 2D
   def normalize(x):
       return x / x.sum(dim=1, keepdim=True)
   
   # ✅ Works for any shape — normalizes last dim
   def normalize(x):
       return x / x.sum(dim=-1, keepdim=True)
   ```

4. **Lazy vs. eager tradeoffs**: Understand when to materialize intermediates (save compute, cost memory) vs. recompute (save memory, cost compute). Gradient checkpointing is exactly this tradeoff.
```

### ===== 引擎 7：错误预判思维 =====

```markdown
### Phase 1.4.5: Failure Mode Anticipation

Before writing a function, ask: "How will this fail?" — then design against those failure modes.

**The Failure Mode Catalog for ML Code**:

| Failure Mode | When It Happens | Prevention |
|-------------|-----------------|-----------|
| **Silent wrong answer** | Broadcast shape mismatch gives result without error | Explicit shape assertions after every transform |
| **Slow poison** | Data leak between train/test undetected | Assert no overlap: `assert len(set(train_ids) & set(test_ids)) == 0` |
| **NaN cascade** | One NaN propagates through entire computation | Check for NaN after loss computation, before backward |
| **Off-by-one** | Indexing error in sequence slicing | Test with sequence length = 1 and 2 |
| **Stale state** | Forgetting `model.eval()` or `optimizer.zero_grad()` | Encapsulate in context manager or method that handles both |
| **Resource leak** | File handles, GPU memory not released | Use `with` statements, explicit `del`, `torch.cuda.empty_cache()` |
| **Config mismatch** | Training config differs from evaluation config | Save and reload config hash, assert match |
| **Randomness leak** | Different behavior between runs despite seeding | Seed ALL sources: Python, NumPy, PyTorch, CUDA, DataLoader workers |

**Pre-mortem technique**: Before writing a complex function, spend 30 seconds imagining it's 3 months later and this function has a bug. What's the most likely bug? Write a test for THAT bug first.
```

### ===== 引擎 8：从第一性原理推导 =====

```markdown
### Phase 1.1.5: First-Principles Algorithm Derivation

When a paper's pseudocode is ambiguous or missing details, don't guess — derive from mathematics.

**Derivation workflow**:

1. **Start from the objective function**: What is being minimized/maximized?
2. **Take gradients analytically**: Write out ∂L/∂θ by hand (or symbolically)
3. **Identify computational structure**: Is it a fixed-point iteration? Gradient descent? EM? Message passing?
4. **Map to code**: Each mathematical operation becomes a tensor operation

**Example: Deriving attention from first principles**

Starting point: "We want to compute a weighted average of values, where weights depend on query-key similarity."

1. Similarity: $s_{ij} = q_i^T k_j$ → `scores = query @ key.T`
2. Normalize to weights: $w_{ij} = \text{softmax}_j(s_{ij})$ → `weights = softmax(scores, dim=-1)`
3. Weighted average: $o_i = \sum_j w_{ij} v_j$ → `output = weights @ value`
4. Scale for stability: $s_{ij} / \sqrt{d_k}$ → `scores = scores / math.sqrt(d_k)`

Result: We've derived the entire attention mechanism from a single English sentence.

**When to use this**: Whenever the paper says "we use [method]" without specifying all implementation details. Go back to the mathematical definition and derive forward.
```

---

## Lead Agent 提示词增强

在 `<academic_research>` 的第 11 条后新增第 12 条：

```
**12. Computational Thinking (Apply for Complex Algorithm Implementation)**

When implementing algorithms or designing systems:
- Math-Code Isomorphism: structure code so it mirrors the mathematical formulation — one equation = one function, subscripts = dimensions, reading code = reading the algorithm
- First-Principles Derivation: when paper details are ambiguous, derive the algorithm from the objective function rather than guessing
- API Design for the Pit of Success: make correct usage the easiest path, wrong usage the hardest
- Code as Narrative: top-down readability, self-documenting names, function-length rule (~40 lines max), headline test
- Property-Based Testing: test mathematical invariants (conservation, bounds, symmetry, equivariance), not just examples
- Computational Graph Thinking: identify parallelism, minimize data movement, fuse operations, think in batch dimensions
- Failure Mode Anticipation: before writing, list likely failure modes and write tests for them first (pre-mortem)
- Complexity Derivation: don't just state O(n²) — derive it, then ask "can the mathematical structure reduce this?"
```

---

## 实施位置总表

| # | 引擎 | 实施文件 | 位置 | 方式 |
|---|------|---------|------|------|
| 1 | 数学-代码同构 | `research-code/SKILL.md` | Phase 1 Step 1.2 后 | 新增 Phase 1.2.5 |
| 2 | 算法复杂度推导 | `research-code/SKILL.md` | Phase 4.5 后 | 新增 Phase 4.5.5 |
| 3 | API"成功之坑" | `research-code/SKILL.md` | Phase 0.5 后 | 新增 Phase 0.5.5 |
| 4 | 代码即叙事 | `research-code/SKILL.md` | Phase 3.3 后 | 新增 Phase 3.3.5 |
| 5 | 性质驱动测试 | `research-code/SKILL.md` | Phase 3.5 (测试金字塔) 后 | 新增 Phase 3.5.5 |
| 6 | 计算图思维 | `research-code/SKILL.md` | Phase 1.2 后 | 新增 Phase 1.2.7 |
| 7 | 错误预判思维 | `research-code/SKILL.md` | Phase 1.4 后 | 新增 Phase 1.4.5 |
| 8 | 第一性原理推导 | `research-code/SKILL.md` | Phase 1.1 后 | 新增 Phase 1.1.5 |
| 9 | Lead Agent 第 12 条 | `prompt.py` | `<academic_research>` | 新增 |

## 约束条件

1. `research-code/SKILL.md` 总长度控制在 900 行以内（当前 728 行，可用 ~172 行）——内容必须极度精炼
2. 每项引擎用最少文字传达最深思想，以代码示例驱动而非文字描述
3. 保持与已有 Phase 编号兼容
4. 不修改 Python 运行时
