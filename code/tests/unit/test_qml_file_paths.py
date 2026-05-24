from pathlib import Path

from PyQt6.QtCore import QUrl

from app.ui.controllers.sampler_controller import SamplerController

# _qml_file_to_path is a @staticmethod on the controller; bind it directly.
_qml_file_to_path = SamplerController._qml_file_to_path


def test_qml_file_url_converts_to_local_path():
    audio = Path("test song.wav").resolve()

    qml_value = QUrl.fromLocalFile(str(audio)).toString()

    assert _qml_file_to_path(qml_value) == audio


def test_plain_path_still_works():
    audio = Path("plain.wav").resolve()

    assert _qml_file_to_path(str(audio)) == audio
