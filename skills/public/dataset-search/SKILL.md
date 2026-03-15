---
name: dataset-search
description: Use this skill when the user needs to find, discover, or download academic and scientific datasets. Searches HuggingFace Datasets, UCI ML Repository, Kaggle, Papers With Code, and other dataset repositories. Trigger on queries like "find a dataset for X", "download dataset", "search for data about Y", "benchmark dataset", "training data for Z", or any request involving dataset discovery for research purposes.
---

# Dataset Search Skill

## Overview

This skill provides a systematic methodology for discovering and accessing academic and scientific datasets. It searches multiple dataset repositories via their APIs and provides structured results with metadata, download instructions, and usage examples.

## When to Use This Skill

**Always load this skill when:**

- User needs to find a dataset for a research task
- User asks about benchmark datasets for a specific domain
- User wants to download data for ML experiments
- User needs to compare available datasets
- User asks about dataset statistics, features, or quality

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **HuggingFace Search** | Search 100K+ datasets on HuggingFace Hub |
| **UCI ML Repository** | Classic ML benchmark datasets |
| **Kaggle Discovery** | Competition and community datasets |
| **Papers With Code** | Datasets linked to research papers and benchmarks |
| **OpenML** | Standardized ML datasets with metadata |
| **Dataset Comparison** | Side-by-side comparison of dataset characteristics |
| **Download Assistance** | Code snippets for loading datasets |
| **Metadata Extraction** | Size, features, splits, license, citation info |

## Workflow

### Step 1: Understand Requirements

| Information | Description | Required |
|------------|-------------|----------|
| **Domain** | NLP, CV, tabular, audio, medical, etc. | Yes |
| **Task** | Classification, regression, generation, etc. | Yes |
| **Size Preference** | Small (dev), medium (research), large (production) | Optional |
| **Language** | For NLP: English, Chinese, multilingual | Optional |
| **License** | Open-source, academic-only, commercial OK | Optional |
| **Format** | CSV, Parquet, images, JSON, etc. | Optional |

### Step 2: Search Datasets

#### Search HuggingFace Datasets

```bash
python -c "
import json, urllib.request, urllib.parse

query = urllib.parse.quote('[SEARCH_QUERY]')
url = f'https://huggingface.co/api/datasets?search={query}&limit=15&sort=downloads&direction=-1'

req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
with urllib.request.urlopen(req, timeout=15) as resp:
    datasets = json.loads(resp.read())

for i, ds in enumerate(datasets, 1):
    name = ds.get('id', 'N/A')
    downloads = ds.get('downloads', 0)
    likes = ds.get('likes', 0)
    tags = ', '.join(ds.get('tags', [])[:5])
    print(f'{i}. {name}')
    print(f'   Downloads: {downloads:,} | Likes: {likes}')
    print(f'   Tags: {tags}')
    print(f'   URL: https://huggingface.co/datasets/{name}')
    print()
"
```

#### Search Papers With Code Datasets

```bash
python -c "
import json, urllib.request, urllib.parse

query = urllib.parse.quote('[SEARCH_QUERY]')
url = f'https://paperswithcode.com/api/v1/datasets/?q={query}&items_per_page=10'

req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())

results = data.get('results', [])
for i, ds in enumerate(results, 1):
    name = ds.get('name', 'N/A')
    full_name = ds.get('full_name', name)
    num_papers = ds.get('num_papers', 0)
    url_str = ds.get('url', 'N/A')
    description = (ds.get('description') or '')[:200]
    print(f'{i}. {full_name}')
    print(f'   Papers using this dataset: {num_papers}')
    print(f'   URL: {url_str}')
    if description:
        print(f'   Description: {description}...')
    print()
"
```

#### Search OpenML Datasets

```bash
python -c "
import json, urllib.request, urllib.parse

query = urllib.parse.quote('[SEARCH_QUERY]')
url = f'https://www.openml.org/api/v1/json/data/list/limit/10/data_name/{query}'

req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    datasets = data.get('data', {}).get('dataset', [])
    for i, ds in enumerate(datasets, 1):
        name = ds.get('name', 'N/A')
        did = ds.get('did', 'N/A')
        n_instances = ds.get('NumberOfInstances', 'N/A')
        n_features = ds.get('NumberOfFeatures', 'N/A')
        n_classes = ds.get('NumberOfClasses', 'N/A')
        print(f'{i}. {name} (ID: {did})')
        print(f'   Instances: {n_instances} | Features: {n_features} | Classes: {n_classes}')
        print(f'   URL: https://www.openml.org/d/{did}')
        print()
except Exception as e:
    print(f'OpenML search returned no results or error: {e}')
"
```

#### Search via Web (UCI, Kaggle, CNKI)

Use `web_search` for repositories without public APIs:

```
web_search("UCI machine learning repository [TOPIC] dataset")
web_search("Kaggle dataset [TOPIC]")
web_search("site:kaggle.com/datasets [TOPIC]")
```

### Step 3: Get Dataset Details

#### HuggingFace Dataset Details

```bash
python -c "
import json, urllib.request

dataset_id = '[DATASET_ID]'  # e.g., 'squad', 'glue', 'imdb'
url = f'https://huggingface.co/api/datasets/{dataset_id}'

req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
with urllib.request.urlopen(req, timeout=15) as resp:
    ds = json.loads(resp.read())

print(f'Dataset: {ds.get(\"id\")}')
print(f'Description: {(ds.get(\"description\") or \"\")[:500]}')
print(f'Downloads: {ds.get(\"downloads\", 0):,}')
print(f'Tags: {\", \".join(ds.get(\"tags\", []))}')
print(f'License: {ds.get(\"license\", \"N/A\")}')
print(f'Citation: {(ds.get(\"citation\") or \"\")[:300]}')

card = ds.get('cardData', {})
if card:
    print(f'Language: {card.get(\"language\", \"N/A\")}')
    print(f'Task: {card.get(\"task_categories\", \"N/A\")}')
    print(f'Size: {card.get(\"size_categories\", \"N/A\")}')
"
```

### Step 4: Generate Loading Code

#### HuggingFace Datasets

```python
from datasets import load_dataset

# Load full dataset
dataset = load_dataset("[DATASET_ID]")

# Load specific split
train = load_dataset("[DATASET_ID]", split="train")
test = load_dataset("[DATASET_ID]", split="test")

# Load specific configuration
dataset = load_dataset("[DATASET_ID]", "[CONFIG_NAME]")

# Preview
print(dataset)
print(dataset["train"][0])
```

#### Scikit-learn Built-in Datasets

```python
from sklearn.datasets import (
    load_iris, load_digits, load_wine, load_breast_cancer,
    fetch_20newsgroups, fetch_california_housing, fetch_openml,
)

# Classic datasets
iris = load_iris(as_frame=True)
print(iris.frame.head())

# Fetch from OpenML by ID
dataset = fetch_openml(data_id=31, as_frame=True)
```

#### Kaggle Datasets

```bash
pip install kaggle
# Requires ~/.kaggle/kaggle.json with API credentials

kaggle datasets download -d [OWNER]/[DATASET_NAME]
unzip [DATASET_NAME].zip -d /mnt/user-data/workspace/data/
```

#### Direct URL Download

```bash
# Download and extract
wget -O /mnt/user-data/workspace/data/dataset.csv "[DIRECT_URL]"

# Or with Python
python -c "
import urllib.request
urllib.request.urlretrieve('[DIRECT_URL]', '/mnt/user-data/workspace/data/dataset.csv')
print('Download complete.')
"
```

### Step 5: Dataset Comparison Report

When the user wants to compare multiple datasets:

```markdown
## Dataset Comparison: [Task/Domain]

| Feature | Dataset A | Dataset B | Dataset C |
|---------|-----------|-----------|-----------|
| **Size** | 10K samples | 50K samples | 1M samples |
| **Features** | 13 numeric | 784 pixels | 300 text |
| **Classes** | 3 | 10 | 2 |
| **License** | MIT | CC-BY-4.0 | Academic |
| **Year** | 2020 | 2018 | 2023 |
| **Papers** | 500+ | 10K+ | 50+ |
| **Language** | English | — | Multilingual |
| **Best For** | Quick tests | Benchmarking | Production |

### Recommendation
Based on [user's requirements], **Dataset B** is recommended because...
```

## Popular Dataset Directories by Domain

| Domain | Recommended Sources |
|--------|-------------------|
| **NLP** | HuggingFace (GLUE, SuperGLUE, SQuAD, MMLU), Papers With Code |
| **Computer Vision** | HuggingFace (ImageNet, CIFAR, COCO), Kaggle, Papers With Code |
| **Tabular/ML** | UCI ML Repository, OpenML, Kaggle |
| **Medical/Bio** | PhysioNet, MIMIC, PubMed datasets |
| **Audio/Speech** | HuggingFace (LibriSpeech, Common Voice), OpenSLR |
| **Recommendation** | MovieLens, Amazon Reviews, Yelp |
| **Time Series** | UCR Archive, M4 Competition, Monash |
| **Graph** | OGB, TU Datasets, SNAP |
| **Chinese NLP** | CLUE, C-Eval, CMMLU, HuggingFace |

### Step 5.5: Find Dataset-Associated Papers via Academic APIs

When searching for datasets that are published alongside research papers, use built-in academic API tools:

- `semantic_scholar_search(query="dataset for X", limit=10)` — Find papers that introduce or benchmark datasets for a specific domain
- `semantic_scholar_paper(paper_id="DOI_or_S2_ID")` — Get full paper details including dataset links in abstracts and references
- `crossref_lookup(doi="10.xxxx/xxxxx")` — Validate dataset DOIs and retrieve authoritative citation metadata

These tools are especially useful for discovering:
- **Benchmark datasets** introduced in seminal papers (e.g., ImageNet, SQuAD, MMLU)
- **Domain-specific datasets** mentioned in survey papers
- **Supplementary data** linked from paper appendices or Data Availability statements

## Integration with Other Skills

- **data-analysis**: Load discovered datasets → run SQL queries
- **statistical-analysis**: Load datasets → run statistical tests
- **experiment-tracking**: Track which datasets were used in experiments
- **research-code**: Generate experiment code using the discovered dataset
- **literature-review**: Find papers associated with datasets

## Output Files

All outputs saved to `/mnt/user-data/outputs/`:
- `dataset_search_results.md` — Search results summary
- `dataset_comparison.md` — Side-by-side comparison
- Loading code snippets are provided inline

Use `present_files` to share outputs with the user.

## Notes

- Always check dataset licenses before use in research
- Verify dataset version and splits match the paper being reproduced
- For large datasets, consider loading subsets first for exploration
- When citing datasets, include the original paper and dataset DOI/URL
- HuggingFace is the most comprehensive source for ML/NLP datasets
- For domain-specific datasets (medical, legal, etc.), also search with `web_search`
