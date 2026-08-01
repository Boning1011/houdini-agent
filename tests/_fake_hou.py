"""Install the smallest hou stub needed for pure-Python contract tests."""

import sys
import types


def install():
    if "hou" in sys.modules:
        return sys.modules["hou"]
    module = types.ModuleType("hou")
    module.__builtins__ = __builtins__
    sys.modules["hou"] = module
    return module
