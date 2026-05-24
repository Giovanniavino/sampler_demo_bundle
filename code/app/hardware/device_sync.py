"""
DeviceManager — desktop-side client for the virtual MPC device.

Speaks the length-prefixed JSON protocol (see app.hardware.wire) over a TCP
socket and exposes one clean Python method per command. Calls are blocking but
fast on localhost; each has a 5 s timeout and up to 3 automatic retries on
network errors. Connection-state changes are surfaced as a Qt signal so the UI
can react.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.models import Pad, Project
from app.hardware.wire import ProtocolError, recv_message, send_message
from app.project.repository import KitRepository, safe_name

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
_TIMEOUT = 5.0
_RETRIES = 3


class DeviceManager(QObject):
    """Client/proxy for the virtual MPC device."""

    connectionChanged = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    def __init__(self, cache_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._host = DEFAULT_HOST
        self._port = DEFAULT_PORT
        self._sd_path = ""
        cache = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir())
        self._kit_cache = cache / "device_kits"
        self._repo = KitRepository()

    # ---- connection ----------------------------------------------------

    def connect(self, host: str = DEFAULT_HOST,
                port: int = DEFAULT_PORT) -> bool:
        """Open a socket to the device. Returns True on success."""
        self._close()
        try:
            sock = socket.create_connection((host, port), timeout=_TIMEOUT)
            sock.settimeout(_TIMEOUT)
        except OSError as e:
            log.warning("Connect to %s:%d failed: %s", host, port, e)
            self._set_connected(False)
            return False
        self._sock = sock
        self._host, self._port = host, port
        self._set_connected(True)
        log.info("Connected to virtual device %s:%d", host, port)
        return True

    def disconnect(self) -> None:
        self._close()
        self._set_connected(False)

    def is_connected(self) -> bool:
        return self._connected

    @property
    def sd_path(self) -> str:
        return self._sd_path

    # ---- commands ------------------------------------------------------

    def ping(self) -> bool:
        return self._request({"cmd": "PING"}).get("status") == "pong"

    def list_kits(self) -> list[str]:
        return self._request({"cmd": "LIST_KITS"}).get("kits", [])

    def list_presets(self) -> list[str]:
        return self._request({"cmd": "LIST_PRESETS"}).get("presets", [])

    def push_kit(self, kit_name: str, project: Project) -> bool:
        """Build a kit locally, then upload all of its files to the device."""
        kit_name = safe_name(kit_name)
        tmp = Path(tempfile.mkdtemp(prefix="kit_push_"))
        try:
            self._repo.save_kit(project, tmp, kit_name)
            files = _read_tree(tmp)
        except Exception as e:                       # noqa: BLE001
            log.error("Building kit '%s' failed: %s", kit_name, e)
            self.errorOccurred.emit(f"could not build kit: {e}")
            return False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        resp = self._request({"cmd": "SAVE_KIT", "kit_name": kit_name,
                               "files": files})
        return resp.get("status") == "saved"

    def load_kit(self, kit_name: str) -> Optional[Project]:
        """Download a kit's files and rebuild the Project from them."""
        kit_name = safe_name(kit_name)
        resp = self._request({"cmd": "LOAD_KIT", "kit_name": kit_name})
        if resp.get("status") != "loaded":
            self.errorOccurred.emit(resp.get("error", "kit load failed"))
            return None
        local = self._kit_cache / kit_name
        shutil.rmtree(local, ignore_errors=True)
        _write_tree(local, resp.get("files", {}))
        try:
            return self._repo.load_kit(local)
        except Exception as e:                       # noqa: BLE001
            log.error("Rebuilding kit '%s' failed: %s", kit_name, e)
            self.errorOccurred.emit(f"could not rebuild kit: {e}")
            return None

    def delete_kit(self, kit_name: str) -> bool:
        resp = self._request({"cmd": "DELETE_KIT",
                               "kit_name": safe_name(kit_name)})
        return resp.get("status") == "deleted"

    def save_preset(self, name: str, pads: list[Pad]) -> bool:
        data = {
            "schema_version": KitRepository.SCHEMA_VERSION,
            "name": name,
            "pads": [
                {"index": p.index, "mode": p.mode.value,
                 "color": p.color, "label": p.label, "group": p.group,
                 "choke_self": p.choke_self}
                for p in pads
            ],
        }
        resp = self._request({"cmd": "SAVE_PRESET",
                               "name": safe_name(name), "data": data})
        return resp.get("status") == "saved"

    def load_preset(self, name: str) -> list[dict]:
        resp = self._request({"cmd": "LOAD_PRESET", "name": safe_name(name)})
        return resp.get("data", {}).get("pads", [])

    def get_storage_info(self) -> dict:
        resp = self._request({"cmd": "GET_STORAGE_INFO"})
        if resp.get("status") == "ok":
            self._sd_path = resp.get("sd_path", "")
            return {"total": resp.get("total", 0),
                    "free": resp.get("free", 0),
                    "used": resp.get("used", 0),
                    "sd_path": self._sd_path}
        return {"total": 0, "free": 0, "used": 0, "sd_path": ""}

    def open_sd_in_explorer(self) -> None:
        """Open the virtual SD card folder in the OS file manager."""
        path = self._sd_path or self.get_storage_info().get("sd_path", "")
        if not path or not Path(path).exists():
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)                       # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as e:
            log.warning("Could not open SD folder: %s", e)

    # ---- internals -----------------------------------------------------

    def _request(self, obj: dict) -> dict:
        """Send a command and return the response, retrying on network errors."""
        last_err = "device unreachable"
        for attempt in range(_RETRIES):
            if self._sock is None and not self.connect(self._host, self._port):
                continue
            try:
                send_message(self._sock, obj)
                return recv_message(self._sock)
            except (OSError, ProtocolError, ValueError) as e:
                last_err = str(e)
                log.warning("Request %s failed (try %d/%d): %s",
                            obj.get("cmd"), attempt + 1, _RETRIES, e)
                self._close()
                self._set_connected(False)
        self.errorOccurred.emit(last_err)
        return {"status": "error", "error": last_err}

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            self.connectionChanged.emit()


def _read_tree(root: Path) -> dict:
    files: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            files[f.relative_to(root).as_posix()] = \
                base64.b64encode(f.read_bytes()).decode("ascii")
    return files


def _write_tree(root: Path, files: dict) -> None:
    for rel, b64 in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(b64))
