#!/bin/sh
# DeerFlow lark-cli init container entrypoint (Pattern A).
#
# Copies the staged sandbox runtime layout into the shared emptyDir the
# provisioner mounts into both this init container and the main sandbox
# container, then exits. The sandbox container then finds the launcher at
# ${LARK_CLI_RUNTIME_DEST}/bin/lark-cli — exactly where
# lark_cli_env_overlay(sandbox_paths=True) points PATH.
set -eu

SRC="/opt/lark-cli"
DEST="${LARK_CLI_RUNTIME_DEST:-/mnt/integrations/lark-cli/runtime}"

if [ ! -x "${SRC}/bin/lark-cli" ]; then
  echo "ERROR: staged runtime missing at ${SRC}/bin/lark-cli" >&2
  exit 1
fi

mkdir -p "${DEST}"
# Copy contents (including the dotfile manifest) into the destination.
cp -a "${SRC}/." "${DEST}/"

echo "Provisioned lark-cli runtime into ${DEST}:"
ls -R "${DEST}"
