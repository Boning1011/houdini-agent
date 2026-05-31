"""
Houdini Agent Bridge — PythonPanel UI.

Provides Start/Stop controls and status display for the bridge server.
This runs inside Houdini and directly imports bridge.server (no HTTP needed).
"""

import sys
import importlib

# Ensure repo root is on sys.path so bridge can be imported
import os
_repo_root = os.environ.get("HOUDINI_AGENT_ROOT") or os.path.dirname(os.path.dirname(__file__))
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

        # --- Peers (other live Houdinis on this machine) ---
        peers_label = QtWidgets.QLabel("Other Houdini bridges on this machine:")
        peers_font = peers_label.font()
        peers_font.setBold(True)
        peers_label.setFont(peers_font)
        layout.addWidget(peers_label)
        self._peers = QtWidgets.QPlainTextEdit()
        self._peers.setReadOnly(True)
        self._peers.setMaximumHeight(80)
        self._peers.setPlaceholderText("(none)")
        layout.addWidget(self._peers)

        # --- Log area ---
        self._log = QtWidgets.QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(200)
        self._log.setPlaceholderText("Server log...")
        layout.addWidget(self._log)

        # --- Refresh timer ---
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.timeout.connect(self._update_peers)
        self._timer.start(2000)  # check every 2s
        self._update_peers()

    def _log_msg(self, msg):
        self._log.appendPlainText(msg)

    def _on_start(self):
        if server._server_instance is not None:
            self._log_msg("Server is already running.")
            return
        # Reload all bridge submodules then server itself to pick up code changes
        from bridge import main_thread
        from bridge.handlers import exec as _h_exec, scene, parms, geometry
        from bridge import handlers as _handlers
        for mod in [main_thread, _h_exec, scene, parms, geometry, _handlers, server]:
            importlib.reload(mod)
        requested = self._port_spin.value()
        try:
            server.start_server(port=requested)
            actual = (server._server_instance.server_address[1]
                      if server._server_instance is not None else None)
            if actual is None:
                self._log_msg(f"Failed to bind any port near {requested}.")
            elif actual == requested:
                self._log_msg(f"Server started on port {actual} (reloaded).")
            else:
                self._log_msg(
                    f"Server started on port {actual} — requested {requested} "
                    f"was busy (another Houdini holds it)."
                )
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

    def _update_peers(self):
        """Show other live bridge servers — anyone listening on a registry port that isn't us."""
        try:
            from bridge.client import _discover_instances
        except ImportError:
            return
        my_port = (server._server_instance.server_address[1]
                   if server._server_instance is not None else None)
        try:
            instances = _discover_instances(timeout=0.5)
        except Exception:
            return
        lines = []
        import os as _os
        my_pid = _os.getpid()
        for inst in sorted(instances, key=lambda x: x.get("port", 0)):
            if inst.get("pid") == my_pid or inst.get("port") == my_port:
                continue
            hip = inst.get("hip_file") or "(unsaved)"
            lines.append(f":{inst.get('port')}  {hip}  (pid {inst.get('pid')})")
        self._peers.setPlainText("\n".join(lines))


def onCreateInterface():
    """Called by Houdini when the PythonPanel is created."""
    return HoudiniAgentPanel()
