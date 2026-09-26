#!/bin/sh
# DeerFlow lark-cli broker entrypoint (Pattern B, issue #4338).
#
# Dispatches to one of two modes on the single stdlib-only module:
#
#   install-shim [dest]   write the shim + runtime marker into the shared
#                         emptyDir (init-container mode), then exit 0.
#   serve                 run the broker HTTP server on loopback (sidecar mode).
#
# The module is copied to /opt/broker/lark_broker.py and run as a script; it has
# no third-party dependencies, so no harness install is needed in this image.
set -eu

MODULE="/opt/broker/lark_broker.py"

case "${1:-serve}" in
  install-shim)
    shift
    exec python3 "${MODULE}" install-shim "$@"
    ;;
  serve)
    exec python3 "${MODULE}"
    ;;
  *)
    echo "Unknown lark-cli-broker mode: ${1:-}" >&2
    echo "Usage: lark-cli-broker [install-shim <dest> | serve]" >&2
    exit 2
    ;;
esac
