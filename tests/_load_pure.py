"""Load a pure component module directly from its file.

Why: importing *any* submodule of custom_components.blue_connect_local (via
`from custom_components...X import Y`) first runs that package's
__init__.py, which does `from .coordinator import BlueConnectCoordinator`,
which in turn imports bleak and homeassistant.components.bluetooth. Result:
even a 100% pure module like chemistry.py becomes unreachable without
installing homeassistant and bleak, even though it needs neither.

So chemistry.py / protocol.py / validation.py / model.py are loaded
directly by file path (importlib), bypassing the package system entirely.
This is safe here because these 4 files have no relative imports of their
own (`from . import ...`): they only depend on the stdlib (math, logging,
typing).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

_COMPONENT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "blue_connect_local"
)


def load_pure_module(filename: str) -> ModuleType:
    stem = filename.removesuffix(".py")
    module_name = f"_blue_connect_local_pure.{stem}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    path = _COMPONENT_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
