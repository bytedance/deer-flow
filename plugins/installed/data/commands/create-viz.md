---
description: Create publication-quality visualizations with Python
argument-hint: "<data source> [chart type]"
---

# /create-viz - Create Visualizations

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Create publication-quality data visualizations using Python. Generates charts from data with best practices for clarity, accuracy, and design.

## Usage

```
/create-viz <data source> [chart type] [additional instructions]
```

## Workflow

### 1. Understand the Request

Determine:

- **Data source**: Query results, pasted data, CSV/Excel file, or data to be queried
- **Chart type**: Explicitly requested or needs to be recommended
- **Purpose**: Exploration, presentation, report, dashboard component
- **Audience**: Technical team, executives, external stakeholders

### 2. Get the Data

**If data warehouse is connected and data needs querying:**
1. Write and execute the query
2. Load results into a pandas DataFrame

**If data is pasted or uploaded:**
1. Parse the data into a pandas DataFrame
2. Clean and prepare as needed (type conversions, null handling)

**If data is from a previous analysis in the conversation:**
1. Reference the existing data

### 3. Select Chart Type

If the user didn't specify a chart type, recommend one based on the data and question:

| Data Relationship | Recommended Chart |
|---|---|
| Trend over time | Line chart |
| Comparison across categories | Bar chart (horizontal if many categories) |
| Part-to-whole composition | Stacked bar or area chart (avoid pie charts unless <6 categories) |
| Distribution of values | Histogram or box plot |
| Correlation between two variables | Scatter plot |
| Two-variable comparison over time | Dual-axis line or grouped bar |
| Geographic data | Choropleth map |
| Ranking | Horizontal bar chart |
| Flow or process | Sankey diagram |
| Matrix of relationships | Heatmap |

Explain the recommendation briefly if the user didn't specify.

### 4. Generate the Visualization

Write Python code using one of these libraries based on the need:

- **matplotlib + seaborn**: Best for static, publication-quality charts. Default choice.
- **plotly**: Best for interactive charts or when the user requests interactivity.

**Code requirements:**

```python
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

# Set professional style
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")

# Create figure with appropriate size
fig, ax = plt.subplots(figsize=(10, 6))

# [chart-specific code]

# Always include:
ax.set_title('Clear, Descriptive Title', fontsize=14, fontweight='bold')
ax.set_xlabel('X-Axis Label', fontsize=11)
ax.set_ylabel('Y-Axis Label', fontsize=11)

# Format numbers appropriately
# - Percentages: '45.2%' not '0.452'
# - Currency: '$1.2M' not '1200000'
# - Large numbers: '2.3K' or '1.5M' not '2300' or '1500000'

# Remove chart junk
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

plt.tight_layout()
plt.savefig('chart_name.png', dpi=150, bbox_inches='tight')
plt.show()
```

### 5. Apply Design Best Practices

**Color:**
- Use a consistent, colorblind-friendly palette
- Use color meaningfully (not decoratively)
- Highlight the key data point or trend with a contrasting color
- Grey out less important reference data

**Typography:**
- Descriptive title that states the insight, not just the metric (e.g., "Revenue grew 23% YoY" not "Revenue by Month")
- Readable axis labels (not rotated 90 degrees if avoidable)
- Data labels on key points when they add clarity

**Layout:**
- Appropriate whitespace and margins
- Legend placement that doesn't obscure data
- Sorted categories by value (not alphabetically) unless there's a natural order

**Accuracy:**
- Y-axis starts at zero for bar charts
- No misleading axis breaks without clear notation
- Consistent scales when comparing panels
- Appropriate precision (don't show 10 decimal places)

### 6. Save and Present

1. Save the chart as a PNG file with descriptive name
2. Display the chart to the user
3. Provide the code used so they can modify it
4. Suggest variations (different chart type, different grouping, zoomed time range)

## Examples

```
/create-viz Show monthly revenue for the last 12 months as a line chart with the trend highlighted
```

```
/create-viz Here's our NPS data by product: [pastes data]. Create a horizontal bar chart ranking products by score.
```

```
/create-viz Query the orders table and create a heatmap of order volume by day-of-week and hour
```

## Tips

- If you want interactive charts (hover, zoom, filter), mention "interactive" and Claude will use plotly
- Specify "presentation" if you need larger fonts and higher contrast
- You can request multiple charts at once (e.g., "create a 2x2 grid of charts showing...")
- Charts are saved to your current directory as PNG files
