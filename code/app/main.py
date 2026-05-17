"""
Application entry point. Run with:
    python -m app.main

Wires the QML UI to the SamplerController and starts the Qt event loop.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

from app.core.logging_setup import setup_logging
from app.ui.controllers.sampler_controller import SamplerController


def main() -> int:
    setup_logging()
    log = logging.getLogger("main")

    app_root = Path(__file__).resolve().parent
    qml_path = app_root / "ui" / "qml" / "Main.qml"
    cache_dir = Path(os.environ.get("SAMPLER_CACHE",
                                     str(app_root.parent / "data" / "cache")))

    # Toggle off demucs if env var set (handy for first-run smoke tests)
    use_demucs = os.environ.get("SAMPLER_NO_DEMUCS") != "1"

    # Native Windows controls do not allow the QML button customizations used here.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    controller = SamplerController(cache_dir=cache_dir, use_demucs=use_demucs)
    engine.rootContext().setContextProperty("controller", controller)
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        log.error("Failed to load QML: %s", qml_path)
        return 1

    log.info("App started")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
