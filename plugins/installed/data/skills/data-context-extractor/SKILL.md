---
name: data-context-extractor
description: >
  Generate or improve a company-specific data analysis skill by extracting tribal knowledge from analysts.

  BOOTSTRAP MODE - Triggers: "Create a data context skill", "Set up data analysis for our warehouse",
  "Help me create a skill for our database", "Generate a data skill for [company]"
  → Discovers schemas, asks key questions, generates initial skill with reference files

  ITERATION MODE - Triggers: "Add context about [domain]", "The skill needs more info about [topic]",
  "Update the data skill with [metrics/tables/terminology]", "Improve the [domain] reference"
  → Loads existing skill, asks targeted questions, appends/updates reference files

  Use when data analysts want Claude to understand their company's specific data warehouse,
  terminology, metrics definitions, and common query patterns.
---

# Data Context Extractor

A meta-skill that extracts company-specific data knowledge from analysts and generates tailored data analysis skills.

## How It Works

This skill has two modes:

1. **Bootstrap Mode**: Create a new data analysis skill from scratch
2. **Iteration Mode**: Improve an existing skill by adding domain-specific reference files

---

## Bootstrap Mode

Use when: User wants to create a new data context skill for their warehouse.

### Phase 1: Database Connection & Discovery

**Step 1: Identify the database type**

Ask: "What data warehouse are you using?"

Common options:
- **BigQuery**
- **Snowflake**
- **PostgreSQL/Redshift**
- **Databricks**

Use `~~data warehouse` tools (query and schema) to connect. If unclear, check available MCP tools in the current session.

**Step 2: Explore the schema**

Use `~~data warehouse` schema tools to:
1. List available datasets/schemas
2. Identify the most important tables (ask user: "Which 3-5 tables do analysts query most often?")
3. Pull schema details for those key tables

Sample exploration queries by dialect:
```sql
-- BigQuery: List datasets
SELECT schema_name FROM INFORMATION_SCHEMA.SCHEMATA

-- BigQuery: List tables in a dataset
SELECT table_name FROM `project.dataset.INFORMATION_SCHEMA.TABLES`

-- Snowflake: List schemas
SHOW SCHEMAS IN DATABASE my_database

-- Snowflake: List tables
SHOW TABLES IN SCHEMA my_schema
```

### Phase 2: Core Questions (Ask These)

After schema discovery, ask these questions conversationally (not all at once):

**Entity Disambiguation (Critical)**
> "When people here say 'user' or 'customer', what exactly do they mean? Are there different types?"

Listen for:
- Multiple entity types (user vs account vs organization)
- Relationships between them (1:1, 1:many, many:many)
- Which ID fields link them together

**Primary Identifiers**
> "What's the main identifier for a [customer/user/account]? Are there multiple IDs for the same entity?"

Listen for:
- Primary keys vs business keys
- UUID vs integer IDs
- Legacy ID systems

**Key Metrics**
> "What are the 2-3 metrics people ask about most? How is each one calculated?"

Listen for:
- Exact formulas (ARR = monthly_revenue × 12)
- Which tables/columns feed each metric
- Time period conventions (trailing 7 days, calendar month, etc.)

**Data Hygiene**
> "What should ALWAYS be filtered out of queries? (test data, fraud, internal users, etc.)"

Listen for:
- Standard WHERE clauses to always include
- Flag columns that indicate exclusions (is_test, is_internal, is_fraud)
- Specific values to exclude (status = 'deleted')

**Common Gotchas**
> "What mistakes do new analysts typically make with this data?"

Listen for:
- Confusing column names
- Timezone issues
- NULL handling quirks
- Historical vs current state tables

### Phase 3: Generate the Skill

Create a skill with this structure:

```
[company]-data-analyst/
├── SKILL.md
└── references/
    ├── entities.md          # Entity definitions and relationships
    ├── metrics.md           # KPI calculations
    ├── tables/              # One file per domain
    │   ├── [domain1].md
    │   └── [domain2].md
    └── dashboards.json      # Optional: existing dashboards catalog
```

**SKILL.md Template**: See `references/skill-template.md`

**SQL Dialect Section**: See `references/sql-dialects.md` and include the appropriate dialect notes.

**Reference File Template**: See `references/domain-template.md`

### Phase 4: Package and Deliver

1. Create all files in the skill directory
2. Package as a zip file
3. Present to user with summary of what was captured

---

## Iteration Mode

Use when: User has an existing skill but needs to add more context.

### Step 1: Load Existing Skill

Ask user to upload their existing skill (zip or folder), or locate it if already in the session.

Read the current SKILL.md and reference files to understand what's already documented.

### Step 2: Identify the Gap

Ask: "What domain or topic needs more context? What queries are failing or producing wrong results?"

Common gaps:
- A new data domain (marketing, finance, product, etc.)
- Missing metric definitions
- Undocumented table relationships
- New terminology

### Step 3: Targeted Discovery

For the identified domain:

1. **Explore relevant tables**: Use `~~data warehouse` schema tools to find tables in that domain
2. **Ask domain-specific questions**:
   - "What tables are used for [domain] analysis?"
   - "What are the key metrics for [domain]?"
   - "Any special filters or gotchas for [domain] data?"

3. **Generate new reference file**: Create `references/[domain].md` using the domain template

### Step 4: Update and Repackage

1. Add the new reference file
2. Update SKILL.md's "Knowledge Base Navigation" section to include the new domain
3. Repackage the skill
4. Present the updated skill to user

---

## Reference File Standards

Each reference file should include:

### For Table Documentation
- **Location**: Full table path
- **Description**: What this table contains, when to use it
- **Primary Key**: How to uniquely identify rows
- **Update Frequency**: How often data refreshes
- **Key Columns**: Table with column name, type, description, notes
- **Relationships**: How this table joins to others
- **Sample Queries**: 2-3 common query patterns

### For Metrics Documentation
- **Metric Name**: Human-readable name
- **Definition**: Plain English explanation
- **Formula**: Exact calculation with column references
- **Source Table(s)**: Where the data comes from
- **Caveats**: Edge cases, exclusions, gotchas

### For Entity Documentation
- **Entity Name**: What it's called
- **Definition**: What it represents in the business
- **Primary Table**: Where to find this entity
- **ID Field(s)**: How to identify it
- **Relationships**: How it relates to other entities
- **Common Filters**: Standard exclusions (internal, test, etc.)

---

## Quality Checklist

Before delivering a generated skill, verify:

- [ ] SKILL.md has complete frontmatter (name, description)
- [ ] Entity disambiguation section is clear
- [ ] Key terminology is defined
- [ ] Standard filters/exclusions are documented
- [ ] At least 2-3 sample queries per domain
- [ ] SQL uses correct dialect syntax
- [ ] Reference files are linked from SKILL.md navigation section
