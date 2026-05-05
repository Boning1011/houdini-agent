"""
Run the Houdini Agent bridge in a headless hython process.

Usage:
    hython /path/to/houdini-agent/scripts/serve_headless.py [--port 8765]

Or, with the package installed (HOUDINI_AGENT_ROOT set):
    hython "$HOUDINI_AGENT_ROOT/scripts/serve_headless.py"

Headless mode runs everything except the GUI-only handlers (/screenshot needs
a Scene Viewer; /ui_state's network-editor lookup degrades to None). Multiple
hython instances on different ports are supported — pass --port.
"""

import argparse
import os
import sys


def _resolve_repo_root():
    env_root = os.environ.get("HOUDINI_AGENT_ROOT")
    if env_root:
        return env_root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description="Run the Houdini Agent bridge headless.")
    ap.add_argument("--port", type=int, default=8765,
                    help="HTTP port (default: 8765)")
    ap.add_argument("--hip", type=str, default=None,
                    help="Optional .hip file to load before serving.")
    args = ap.parse_args()

    repo_root = _resolve_repo_root()
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    if args.hip:
        import hou
        hou.hipFile.load(args.hip, suppress_save_prompt=True)
        print(f"[houdini-agent] Loaded {args.hip}")

    from bridge.server import serve_headless
    serve_headless(port=args.port)


if __name__ == "__main__":
    main()
