"""Tests for the virtual device + DeviceManager sync layer."""

import threading

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("PyQt6.QtCore")
from PyQt6.QtCore import QCoreApplication

from app.core.models import (
    Pad, PadBank, PadMode, Project, Sample, Stem, StemType,
)
from app.hardware.device_sync import DeviceManager
from app.hardware.virtual_device import DeviceServer, VirtualDevice


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def device_port(tmp_path):
    """Start a virtual device on an ephemeral port; yield the port."""
    device = VirtualDevice(sd_root=tmp_path / "sd")
    server = DeviceServer(device, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    server.server_close()


def _manager(tmp_path, port) -> DeviceManager:
    dm = DeviceManager(cache_dir=tmp_path / "cache")
    assert dm.connect("127.0.0.1", port)
    return dm


def _project_with_stem(tmp_path) -> Project:
    wav = tmp_path / "src" / "drums.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav), np.zeros(4410, dtype="float32"), 22050)
    stem = Stem(stem_type=StemType.DRUMS, path=wav,
                sample_rate=22050, duration_samples=4410)
    sample = Sample(name="hit", source_stem_id=stem.id,
                    start_sample=0, end_sample=2000)
    pad = Pad(index=0, sample_id=sample.id, mode=PadMode.LOOP, group=1)
    bank = PadBank(name="A", pads=[pad])
    return Project(name="Test Kit", stems=[stem], samples=[sample],
                   banks=[bank], active_bank_id=bank.id)


def test_connect_and_ping(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    assert dm.is_connected()
    assert dm.ping()
    dm.disconnect()
    assert not dm.is_connected()


def test_connect_failure_no_server(qt_app, tmp_path):
    dm = DeviceManager(cache_dir=tmp_path / "cache")
    assert not dm.connect("127.0.0.1", 1)        # nothing listens on port 1
    assert not dm.is_connected()


def test_list_empty_kits(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    assert dm.list_kits() == []


def test_push_kit_then_list(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    assert dm.push_kit("my_kit", _project_with_stem(tmp_path))
    assert "my_kit" in dm.list_kits()


def test_push_then_load_kit_roundtrip(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    assert dm.push_kit("rt_kit", _project_with_stem(tmp_path))

    loaded = dm.load_kit("rt_kit")
    assert loaded is not None
    assert loaded.name == "Test Kit"
    assert len(loaded.stems) == 1
    assert loaded.stems[0].path.exists()
    pad = loaded.banks[0].pads[0]
    assert pad.mode == PadMode.LOOP
    assert pad.group == 1


def test_delete_kit(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    dm.push_kit("doomed", _project_with_stem(tmp_path))
    assert "doomed" in dm.list_kits()
    assert dm.delete_kit("doomed")
    assert "doomed" not in dm.list_kits()


def test_load_missing_kit_returns_none(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    assert dm.load_kit("ghost") is None


def test_preset_save_load(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    pads = [Pad(index=0, mode=PadMode.GATE, group=3, label="X")]
    assert dm.save_preset("my_preset", pads)
    assert "my_preset" in dm.list_presets()
    loaded = dm.load_preset("my_preset")
    assert loaded[0]["mode"] == "gate"
    assert loaded[0]["group"] == 3


def test_storage_info(qt_app, device_port, tmp_path):
    dm = _manager(tmp_path, device_port)
    info = dm.get_storage_info()
    assert info["total"] > 0
    assert info["sd_path"]


def test_request_after_drop_reconnects(qt_app, device_port, tmp_path):
    """A dropped socket is transparently re-established on the next call."""
    dm = _manager(tmp_path, device_port)
    assert dm.ping()
    dm._close()                                  # simulate a dropped link
    assert dm.ping()                             # retry path reconnects
