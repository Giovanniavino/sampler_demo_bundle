"""
Virtual MPC device — simulates the standalone hardware.

Creates a temporary folder that stands in for the device's SD card and serves
a JSON-over-TCP protocol, so the desktop app can develop and test the whole
sync / storage layer before the physical device exists.

Run it standalone in its own terminal:

    python -m app.hardware.virtual_device

It prints the listen address and the virtual SD card path, then serves until
interrupted (Ctrl+C).
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
import socketserver
import tempfile
import threading
from pathlib import Path

from app.hardware.wire import ProtocolError, recv_message, send_message
from app.project.repository import safe_name

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555


class VirtualDevice:
    """Owns the virtual SD card and handles protocol commands."""

    def __init__(self, sd_root: Path | None = None):
        if sd_root is None:
            sd_root = Path(tempfile.mkdtemp(prefix="virtual_mpc_"))
        self.sd_root = Path(sd_root)
        self.kits_dir = self.sd_root / "kits"
        self.presets_dir = self.sd_root / "presets"
        self.projects_dir = self.sd_root / "projects"
        for d in (self.kits_dir, self.presets_dir, self.projects_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._state: dict = {}
        self._lock = threading.Lock()
        log.info("Virtual SD card ready at %s", self.sd_root)

    # ---- dispatch ------------------------------------------------------

    def handle(self, request: dict) -> dict:
        """Route one request to its handler; never raises."""
        cmd = str(request.get("cmd", ""))
        handler = getattr(self, f"_cmd_{cmd.lower()}", None)
        if handler is None:
            return {"status": "error", "error": f"unknown command: {cmd}"}
        try:
            with self._lock:
                result = handler(request)
            log.info("%s -> %s", cmd, result.get("status"))
            return result
        except Exception as e:                       # noqa: BLE001
            log.exception("Command %s failed", cmd)
            return {"status": "error", "error": str(e)}

    # ---- commands ------------------------------------------------------

    def _cmd_ping(self, req: dict) -> dict:
        return {"status": "pong"}

    def _cmd_list_kits(self, req: dict) -> dict:
        kits = sorted(d.name for d in self.kits_dir.iterdir()
                      if d.is_dir() and (d / "kit.json").exists())
        return {"status": "ok", "kits": kits}

    def _cmd_list_presets(self, req: dict) -> dict:
        presets = sorted(f.stem for f in self.presets_dir.glob("*.json"))
        return {"status": "ok", "presets": presets}

    def _cmd_save_kit(self, req: dict) -> dict:
        name = safe_name(req["kit_name"])
        kit_dir = self.kits_dir / name
        if kit_dir.exists():
            shutil.rmtree(kit_dir)
        files = req.get("files", {})
        for rel, b64 in files.items():
            self._write_rel(kit_dir, rel, b64)
        return {"status": "saved", "kit": name, "path": str(kit_dir)}

    def _cmd_load_kit(self, req: dict) -> dict:
        name = safe_name(req["kit_name"])
        kit_dir = self.kits_dir / name
        if not (kit_dir / "kit.json").exists():
            return {"status": "error", "error": f"no kit '{name}'"}
        return {"status": "loaded", "kit": name,
                "files": self._read_tree(kit_dir)}

    def _cmd_delete_kit(self, req: dict) -> dict:
        name = safe_name(req["kit_name"])
        kit_dir = self.kits_dir / name
        if not kit_dir.exists():
            return {"status": "error", "error": f"no kit '{name}'"}
        shutil.rmtree(kit_dir)
        return {"status": "deleted", "kit": name}

    def _cmd_save_preset(self, req: dict) -> dict:
        name = safe_name(req["name"])
        path = self.presets_dir / f"{name}.json"
        path.write_text(json.dumps(req.get("data", {}), indent=2),
                        encoding="utf-8")
        return {"status": "saved", "preset": name}

    def _cmd_load_preset(self, req: dict) -> dict:
        name = safe_name(req["name"])
        path = self.presets_dir / f"{name}.json"
        if not path.exists():
            return {"status": "error", "error": f"no preset '{name}'"}
        return {"status": "loaded", "preset": name,
                "data": json.loads(path.read_text(encoding="utf-8"))}

    def _cmd_push_file(self, req: dict) -> dict:
        self._write_rel(self.sd_root, req["path"], req["data"])
        return {"status": "written", "path": req["path"]}

    def _cmd_pull_file(self, req: dict) -> dict:
        target = self._safe_join(self.sd_root, req["path"])
        if not target.is_file():
            return {"status": "error", "error": "no such file"}
        return {"status": "ok", "path": req["path"],
                "data": base64.b64encode(target.read_bytes()).decode("ascii")}

    def _cmd_get_state(self, req: dict) -> dict:
        return {"status": "ok", "state": dict(self._state)}

    def _cmd_set_state(self, req: dict) -> dict:
        self._state = dict(req.get("state", {}))
        return {"status": "applied"}

    def _cmd_get_storage_info(self, req: dict) -> dict:
        usage = shutil.disk_usage(self.sd_root)
        used = sum(f.stat().st_size for f in self.sd_root.rglob("*")
                   if f.is_file())
        return {"status": "ok", "total": usage.total, "free": usage.free,
                "used": used, "sd_path": str(self.sd_root)}

    # ---- helpers -------------------------------------------------------

    def _write_rel(self, base: Path, rel: str, b64: str) -> None:
        target = self._safe_join(base, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(b64))

    @staticmethod
    def _read_tree(root: Path) -> dict:
        files: dict[str, str] = {}
        for f in sorted(root.rglob("*")):
            if f.is_file():
                rel = f.relative_to(root).as_posix()
                files[rel] = base64.b64encode(f.read_bytes()).decode("ascii")
        return files

    @staticmethod
    def _safe_join(base: Path, rel: str) -> Path:
        """Join rel onto base, refusing paths that escape the device root."""
        base_resolved = base.resolve()
        target = (base_resolved / rel).resolve()
        if target != base_resolved and base_resolved not in target.parents:
            raise ProtocolError(f"path escapes device root: {rel}")
        return target


# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------

class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        device: VirtualDevice = self.server.device      # type: ignore[attr-defined]
        peer = self.client_address
        log.info("Client connected: %s", peer)
        try:
            while True:
                try:
                    request = recv_message(self.request)
                except ProtocolError:
                    break                                # client disconnected
                send_message(self.request, device.handle(request))
        except (ConnectionError, OSError) as e:
            log.info("Client %s dropped: %s", peer, e)
        log.info("Client disconnected: %s", peer)


class DeviceServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, device: VirtualDevice,
                 host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        super().__init__((host, port), _Handler)
        self.device = device


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    device = VirtualDevice()
    server = DeviceServer(device)
    host, port = server.server_address
    print(f"Virtual MPC started on {host}:{port}")
    print(f"SD Card: {device.sd_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
