from deerflow.config import configure_paths
from deerflow.config.paths import get_paths


def test_config_package_exports_configure_paths(tmp_path):
    configure_paths(tmp_path)
    assert get_paths().base_dir == tmp_path.resolve()
