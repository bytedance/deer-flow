from __future__ import annotations

import sys
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

DATA_ANALYST_SCRIPTS = Path(__file__).resolve().parents[2] / "data-analyst" / "scripts"


@contextmanager
def _prepend_sys_path(path: Path):
    path_str = str(path)
    sys.path.insert(0, path_str)
    try:
        yield
    finally:
        try:
            sys.path.remove(path_str)
        except ValueError:
            pass


def load_data_analyst_module(filename: str, module_name: str) -> ModuleType:
    target = DATA_ANALYST_SCRIPTS / filename
    if not target.exists():
        raise FileNotFoundError(f"data-analyst script not found: {target}")

    with _prepend_sys_path(DATA_ANALYST_SCRIPTS):
        spec = spec_from_file_location(module_name, target)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load module spec for {target}")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)

    natural_name = filename.removesuffix(".py")
    sys.modules.setdefault(natural_name, module)

    return module
