#!/bin/bash
DEER_FLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DEER_FLOW_ROOT
exec docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml up
