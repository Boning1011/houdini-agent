"""
Houdini Agent Bridge — PythonPanel UI.

Provides Start/Stop controls and status display for the bridge server.
This runs inside Houdini and directly imports bridge.server (no HTTP needed).
"""

import sys
import importlib

# Ensure repo root is on sys.path so bridge can be imported
_repo_root = r"C:\Users\vvox\Documents\GitHub\houdini-agent"
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from PySide6 import QtWidgets, QtCore, QtGui
from bridge import server


class HoudiniAgentPanel(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._update_status()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Status bar ---
        status_row = QtWidgets.QHBoxLayout()
        self._status_dot = QtWidgets.QLabel("\u25cf")  # filled circle
        self._status_dot.setFixedWidth(20)
        self._status_label = QtWidgets.QLabel("Stopped")
        font = self._status_label.font()
        font.setBold(True)
        self._status_label.setFont(font)
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        # --- Port input ---
        port_row = QtWidgets.QHBoxLayout()
        port_row.addWidget(QtWidgets.QLabel("Port:"))
        self._port_spin = QtWidgets.QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(server.DEFAULT_PORT)
        port_row.addWidget(self._port_spin)
        port_row.addStretch()
        layout.addLayout(port_row)

        # --- Buttons ---
        btn_row = QtWidgets.QHBoxLayout()
        self._start_btn = QtWidgets.QPushButton("Start Server")
        self._stop_btn = QtWidgets.QPushButton("Stop Server")
        self._start_btn.setMinimumHeight(32)
        self._stop_btn.setMinimumHeight(32)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        layout.addLayout(btn_row)

        # --- Log area ---
        self._log = QtWidgets.QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(200)
        self._log.setPlaceholderText("Server log...")
        layout.addWidget(self._log)

        # --- Refresh timer ---
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(2000)  # check every 2s

    def _log_msg(self, msg):
        self._log.appendPlainText(msg)

    def _on_start(self):
        if server._server_instance is not None:
            self._log_msg("Server is already running.")
            return
        # Reload module to pick up code changes from disk
        importlib.reload(server)
        port = self._port_spin.value()
        try:
            server.start_server(port=port)
            self._log_msg(f"Server started on port {port} (reloaded).")
        except Exception as e:
            self._log_msg(f"Failed to start: {e}")
        self._update_status()

    def _on_stop(self):
        if server._server_instance is None:
            self._log_msg("No server running.")
            return
        try:
            server.stop_server()
            self._log_msg("Server stopped.")
        except Exception as e:
            self._log_msg(f"Failed to stop: {e}")
        self._update_status()

    def _update_status(self):
        running = server._server_instance is not None
        if running:
            port = server._server_instance.server_address[1]
            self._status_dot.setStyleSheet("color: #4CAF50; font-size: 18px;")
            self._status_label.setText(f"Running on :{port}")
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._port_spin.setEnabled(False)
        else:
            self._status_dot.setStyleSheet("color: #F44336; font-size: 18px;")
            self._status_label.setText("Stopped")
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._port_spin.setEnabled(True)


def onCreateInterface():
    """Called by Houdini when the PythonPanel is created."""
    return HoudiniAgentPanel()
