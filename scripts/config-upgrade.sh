#!/usr/bin/env bash
#
# config-upgrade.sh - Upgrade config.yaml to match config.example.yaml
#
# 1. Runs version-specific migrations (value replacements, renames, etc.)
# 2. Merges missing fields from the example into the user config
# 3. Backs up config.yaml to config.yaml.bak before modifying.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE="$REPO_ROOT/config.example.yaml"

# Resolve config.yaml location: env var > backend/ > repo root
if [ -n "$DEER_FLOW_CONFIG_PATH" ] && [ -f "$DEER_FLOW_CONFIG_PATH" ]; then
    CONFIG="$DEER_FLOW_CONFIG_PATH"
elif [ -f "$REPO_ROOT/backend/config.yaml" ]; then
    CONFIG="$REPO_ROOT/backend/config.yaml"
elif [ -f "$REPO_ROOT/config.yaml" ]; then
    CONFIG="$REPO_ROOT/config.yaml"
else
    CONFIG=""
fi

if [ ! -f "$EXAMPLE" ]; then
    echo "✗ config.example.yaml not found at $EXAMPLE"
    exit 1
fi

if [ -z "$CONFIG" ]; then
    echo "No config.yaml found — creating from example..."
    cp "$EXAMPLE" "$REPO_ROOT/config.yaml"
    echo "OK config.yaml created. Please review and set your API keys."
    exit 0
fi

# Use inline Python to do migrations + recursive merge with PyYAML
if command -v cygpath >/dev/null 2>&1; then
    CONFIG_WIN="$(cygpath -w "$CONFIG")"
    EXAMPLE_WIN="$(cygpath -w "$EXAMPLE")"
else
    CONFIG_WIN="$CONFIG"
    EXAMPLE_WIN="$EXAMPLE"
fi

cd "$REPO_ROOT/backend" && CONFIG_WIN_PATH="$CONFIG_WIN" EXAMPLE_WIN_PATH="$EXAMPLE_WIN" uv run python -c "
import os
import sys, shutil, copy, re
from pathlib import Path

import yaml

config_path = Path(os.environ['CONFIG_WIN_PATH'])
example_path = Path(os.environ['EXAMPLE_WIN_PATH'])

with open(config_path, encoding='utf-8') as f:
    raw_text = f.read()
    user = yaml.safe_load(raw_text) or {}

with open(example_path, encoding='utf-8') as f:
    example = yaml.safe_load(f) or {}

user_version = user.get('config_version', 0)
example_version = example.get('config_version', 0)

if user_version >= example_version:
    print(f'OK config.yaml is already up to date (version {user_version}).')
    sys.exit(0)

print(f'Upgrading config.yaml: version {user_version} -> {example_version}')
print()

# ── Migrations ───────────────────────────────────────────────────────────
# Each migration targets a specific version upgrade.
# 'replacements': list of (old_string, new_string) applied to the raw YAML text.
#   This handles value changes that a dict merge cannot catch.
# 'data_transform': callable applied to the parsed config after text migrations.

RAGFLOW_PROVIDER_KEYS = (
    'base_url',
    'api_key',
    'timeout',
    'page_size',
    'similarity_threshold',
    'vector_similarity_weight',
    'top_k',
    'max_chars_per_chunk',
    'max_total_chars',
)


def migrate_knowledge_provider_settings(data):
    # Move legacy RAGFlow settings to the provider tool and remove them from the generic block.
    knowledge_base = data.get('knowledge_base')
    tools = data.get('tools')
    target = None
    if isinstance(tools, list):
        target = next(
            (
                tool
                for tool in tools
                if isinstance(tool, dict)
                and tool.get('name') == 'knowledge_search'
                and tool.get('use') == 'deerflow.community.ragflow.tools:knowledge_search_tool'
            ),
            None,
        )

    changes = []
    # Before v42, a tools-only knowledge configuration was valid and enabled by
    # the presence of the provider tool itself. Preserve that behavior when the
    # v42 merge would otherwise add the example's ``enabled: false`` gate.
    if not isinstance(knowledge_base, dict):
        if target is not None and any(key in target for key in RAGFLOW_PROVIDER_KEYS):
            data['knowledge_base'] = {'enabled': True}
            changes.append('knowledge_base.enabled set to true (preserved tools.knowledge_search configuration)')
        return changes

    if 'enabled' not in knowledge_base and target is not None and any(key in target for key in RAGFLOW_PROVIDER_KEYS):
        knowledge_base['enabled'] = True
        changes.append('knowledge_base.enabled set to true (preserved tools.knowledge_search configuration)')

    for key in RAGFLOW_PROVIDER_KEYS:
        if key not in knowledge_base:
            continue
        if target is None:
            changes.append(f'knowledge_base.{key} removed (no RAGFlow knowledge_search tool configured)')
        elif key in target:
            changes.append(f'knowledge_base.{key} removed (tools.knowledge_search.{key} preserved)')
        else:
            target[key] = knowledge_base[key]
            changes.append(f'knowledge_base.{key} -> tools.knowledge_search.{key}')
        del knowledge_base[key]
    return changes


MIGRATIONS = {
    1: {
        'description': 'Rename src.* module paths to deerflow.*',
        'replacements': [
            ('src.community.', 'deerflow.community.'),
            ('src.sandbox.', 'deerflow.sandbox.'),
            ('src.models.', 'deerflow.models.'),
            ('src.tools.', 'deerflow.tools.'),
        ],
    },
    42: {
        'description': 'Move provider-specific RAGFlow settings from knowledge_base to the knowledge_search tool',
        'data_transform': migrate_knowledge_provider_settings,
    },
}

# Apply migrations in order for versions (user_version, example_version]
migrated = []
for version in range(user_version + 1, example_version + 1):
    migration = MIGRATIONS.get(version)
    if not migration:
        continue
    desc = migration.get('description', f'Migration to v{version}')
    for old, new in migration.get('replacements', []):
        if old in raw_text:
            raw_text = raw_text.replace(old, new)
            migrated.append(f'{old} -> {new}')

# Re-parse after text migrations
user = yaml.safe_load(raw_text) or {}

# Apply structured migrations to the parsed config.
for version in range(user_version + 1, example_version + 1):
    migration = MIGRATIONS.get(version)
    transform = migration.get('data_transform') if migration else None
    if transform:
        migrated.extend(transform(user))

if migrated:
    print(f'Applied {len(migrated)} migration(s):')
    for m in migrated:
        print(f'  ~ {m}')
    print()

# ── Merge missing fields ─────────────────────────────────────────────────

added = []

def merge(target, source, path=''):
    \"\"\"Recursively merge source into target, adding missing keys only.\"\"\"
    for key, value in source.items():
        key_path = f'{path}.{key}' if path else key
        if key not in target:
            target[key] = copy.deepcopy(value)
            added.append(key_path)
        elif isinstance(value, dict) and isinstance(target[key], dict):
            merge(target[key], value, key_path)

merge(user, example)

# Always update config_version
user['config_version'] = example_version

# ── Write ─────────────────────────────────────────────────────────────────

backup = config_path.with_suffix('.yaml.bak')
shutil.copy2(config_path, backup)
print(f'Backed up to {backup.name}')

with open(config_path, 'w', encoding='utf-8') as f:
    yaml.dump(user, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

if added:
    print(f'Added {len(added)} new field(s):')
    for a in added:
        print(f'  + {a}')

if not migrated and not added:
    print('No changes needed (version bumped only).')

print()
print(f'OK config.yaml upgraded to version {example_version}.')
print('  Please review the changes and set any new required values.')
"
