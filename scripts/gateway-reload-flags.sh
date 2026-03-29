#!/usr/bin/env bash

set -euo pipefail

cat <<'EOF'
--reload
--reload-include=*.yaml
--reload-include=.env
--reload-exclude=.deer-flow
--reload-exclude=.deer-flow/*
--reload-exclude=*/.deer-flow/*
--reload-exclude=*/user-data/outputs/*
EOF
