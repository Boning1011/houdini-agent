"""Run a disposable headless bridge for cross-version contract tests."""

import sys

from bridge.server import serve_headless


if __name__ == "__main__":
    serve_headless(port=int(sys.argv[1]))
