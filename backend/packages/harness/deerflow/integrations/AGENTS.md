# Managed Integrations

`lark_broker.install_shim()` publishes each runtime file through a temporary
file: write UTF-8 text, set the final mode, fsync, then `os.replace`. Publish the
shim and launcher as `0o755` and the non-secret runtime marker as `0o644`; do not
chmod after replacement. Permission failures preserve the previous file and
remove the temporary file. Coverage: `backend/tests/test_lark_shim_atomic.py`.
