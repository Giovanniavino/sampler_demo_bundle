from pathlib import Path

from PyQt6.QtCore import QUrl

from app.ui.controllers.sampler_controller import _qml_file_to_path


def test_qml_file_url_converts_to_local_path(tmp_path: Path):
    audio = tmp_path / "test song.wav"
    audio.write_bytes(b"placeholder")

    qml_value = QUrl.fromLocalFile(str(audio)).toString()

    assert _qml_file_to_path(qml_value) == audio


def test_plain_path_still_works(tmp_path: Path):
    audio = tmp_path / "plain.wav"
    audio.write_bytes(b"placeholder")

    assert _qml_file_to_path(str(audio)) == audio
