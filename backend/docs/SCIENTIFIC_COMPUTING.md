# Scientific Computing in Sandbox

When using statistical-analysis, data-analysis, or research-code skills,
the sandbox environment needs these Python packages.

## Required Packages

```bash
pip install numpy pandas scipy statsmodels scikit-learn \
    pingouin lifelines matplotlib seaborn openpyxl sympy
```

### Package Purposes

| Package | Purpose |
|---------|---------|
| `numpy` | Numerical computing, array operations |
| `pandas` | Data manipulation, CSV/Excel I/O |
| `scipy` | Statistical tests, optimization, signal processing |
| `statsmodels` | Regression, time series, statistical models |
| `scikit-learn` | Machine learning, preprocessing, metrics |
| `pingouin` | Simplified statistical testing with effect sizes |
| `lifelines` | Survival analysis (Kaplan-Meier, Cox PH) |
| `matplotlib` | Base plotting library |
| `seaborn` | Statistical visualization |
| `openpyxl` | Excel file read/write support for pandas |
| `sympy` | Symbolic mathematics |

## For Local Sandbox

Install these packages in the same Python environment that the backend uses:

```bash
# From the project root
cd backend
uv add numpy pandas scipy statsmodels scikit-learn pingouin lifelines matplotlib seaborn openpyxl sympy
```

Or if using pip directly:

```bash
pip install -r requirements-scientific.txt
```

## For Docker Sandbox (AIO)

The AIO sandbox image includes most scientific packages by default.
If a package is missing, add it to the sandbox Dockerfile or install
at runtime via the `bash` tool:

```python
bash("pip install pingouin lifelines")
```

## Verification

To verify that all required packages are available in the sandbox,
run the following command:

```python
bash("python -c \"import numpy, pandas, scipy, statsmodels, sklearn, pingouin, matplotlib, seaborn; print('All scientific packages available')\"")
```
