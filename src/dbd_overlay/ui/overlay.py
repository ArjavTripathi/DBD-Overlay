"""QML-based overlay windows (map overlay now, streak HUD in M6).

Python owns the state; QML only draws. Python sets properties on the QML root
object and listens to its signals.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QSize, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickImageProvider

log = logging.getLogger(__name__)

QML_DIR = Path(__file__).parent / "qml"


def platform_variant() -> str:
    """Which PlatformWindow.qml to use. Call after the Q(Gui)Application exists."""
    if sys.platform.startswith("linux") and QGuiApplication.platformName() == "wayland":
        return "layershell"
    return "generic"


def load_image(path: Path, max_size: QSize | None = None) -> QImage | None:
    """Decode with OpenCV (handles PNG/WebP/JPG without extra Qt plugins).

    Downscaled to max_size (keeping aspect) so a 2000x2200 map doesn't sit in
    memory at full size when it's drawn at 500 px.
    """
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        log.warning("cannot decode image %s", path)
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    if max_size is not None:
        h, w = img.shape[:2]
        scale = min(max_size.width() / w, max_size.height() / h, 1.0)
        if scale < 1.0:
            img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    # .copy(): QImage would otherwise point into numpy memory that gets freed.
    return QImage(img.data, w, h, img.strides[0], QImage.Format.Format_RGBA8888).copy()


class ImageStore(QQuickImageProvider):
    """Serves images to QML as image://<name>/<key>."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._images: dict[str, QImage] = {}

    def put(self, key: str, image: QImage) -> None:
        self._images[key] = image

    def requestImage(self, id: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802 (Qt API)
        return self._images.get(id, QImage())


def create_engine(variant: str) -> tuple[QQmlEngine, ImageStore]:
    engine = QQmlEngine()
    # Puts the right `DbdPlatform` module first on the import path.
    engine.addImportPath(str(QML_DIR / "platform" / variant))
    store = ImageStore()
    engine.addImageProvider("img", store)
    log.info("overlay windows: %s", variant)
    return engine, store


class OverlayWindow(QObject):
    """Python handle for qml/OverlayWindow.qml."""

    edit_done = Signal()

    def __init__(self, engine: QQmlEngine, store: ImageStore, geometry: tuple[int, int, int, int], opacity: float) -> None:
        super().__init__()
        self._store = store
        self._image_rev = 0
        # Keep the component alive as long as the window.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / "OverlayWindow.qml")))
        x, y, w, h = geometry
        self.root = self._component.createWithInitialProperties(
            {"posX": x, "posY": y, "width": w, "height": h, "contentOpacity": opacity, "visible": False}
        )
        if self.root is None:
            errors = "; ".join(e.toString() for e in self._component.errors())
            raise RuntimeError(f"overlay QML failed: {errors} (on Linux: pacman -S layer-shell-qt)")
        # Objects created from QML default to JavaScript ownership, so the QML
        # garbage collector may delete them at any time. We own this one.
        QQmlEngine.setObjectOwnership(self.root, QQmlEngine.ObjectOwnership.CppOwnership)
        self.root.editDone.connect(self.edit_done)

    def set_image(self, image: QImage | None) -> None:
        if image is None:
            self.root.setProperty("imageSource", "")
            return
        # A new key each time: QML caches by URL.
        self._image_rev += 1
        key = f"map-{self._image_rev}"
        self._store.put(key, image)
        self.root.setProperty("imageSource", f"image://img/{key}")

    def set_shown(self, shown: bool) -> None:
        if bool(self.root.property("visible")) != shown:
            self.root.setProperty("visible", shown)

    def set_edit_mode(self, editing: bool) -> None:
        self.root.setProperty("editMode", editing)

    def set_placeholder(self, text: str) -> None:
        self.root.setProperty("placeholder", text)

    def geometry(self) -> tuple[int, int, int, int]:
        r = self.root
        return int(r.property("posX")), int(r.property("posY")), int(r.property("width")), int(r.property("height"))

    def size(self) -> QSize:
        return QSize(int(self.root.property("width")), int(self.root.property("height")))
