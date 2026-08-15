"""Screen capture backends for Wayland (GNOME/wlroots/KDE) and X11.

capture_full_desktop() returns a QImage covering the whole virtual desktop
(all monitors stitched together) or raises CaptureError.
"""

import os
import shutil
import subprocess
import tempfile

from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusVariant
from PyQt6.QtGui import QGuiApplication, QImage, QPainter


class CaptureError(RuntimeError):
    pass


def _on_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _load(path: str):
    img = QImage(path)
    try:
        os.unlink(path)
    except OSError:
        pass
    return img if not img.isNull() else None


_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"


class _PortalResponse(QObject):
    """Collects the portal Request::Response signal into a QEventLoop.

    The slot receives the raw QDBusMessage: QtDBus drops signals whose
    demarshalled types don't exactly match the slot signature (the real
    signal is `u a{sv}`), so we parse the arguments ourselves.
    """

    def __init__(self):
        super().__init__()
        self.loop = QEventLoop()
        self.request_path: str | None = None
        self.uri: str | None = None
        self.done = False

    @pyqtSlot("QDBusMessage")
    def on_response(self, message):
        if self.request_path and message.path() != self.request_path:
            return  # another app's portal request
        args = message.arguments()
        if len(args) == 2 and args[0] == 0 and isinstance(args[1], dict):
            uri = args[1].get("uri")
            self.uri = str(uri) if uri else None
        self.done = True
        self.loop.quit()


def _capture_portal():
    """XDG desktop portal Screenshot (the standard Wayland API, silent)."""
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None

    handler = _PortalResponse()
    # Signal sender is the portal's *unique* bus name, so match any sender
    # and filter on the request object path instead.
    if not bus.connect(None, None, "org.freedesktop.portal.Request",
                       "Response", handler.on_response):
        return None

    msg = QDBusMessage.createMethodCall(
        _PORTAL_BUS, _PORTAL_PATH,
        "org.freedesktop.portal.Screenshot", "Screenshot",
    )
    msg.setArguments(["", {"interactive": QDBusVariant(False)}])
    reply = bus.call(msg)
    if (reply.type() == QDBusMessage.MessageType.ErrorMessage
            or not reply.arguments()):
        bus.disconnect(None, None, "org.freedesktop.portal.Request",
                       "Response", handler.on_response)
        return None

    handler.request_path = str(reply.arguments()[0])
    QTimer.singleShot(20000, handler.loop.quit)  # safety timeout
    handler.loop.exec()
    bus.disconnect(None, None, "org.freedesktop.portal.Request",
                   "Response", handler.on_response)
    if not handler.done or not handler.uri:
        return None
    path = QUrl(handler.uri).toLocalFile()
    return _load(path) if path else None


def _capture_gnome_shell():
    """GNOME Shell's private D-Bus screenshot API (silent, all monitors)."""
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    fd, path = tempfile.mkstemp(suffix=".png", prefix="quicksnipp-")
    os.close(fd)
    msg = QDBusMessage.createMethodCall(
        "org.gnome.Shell",
        "/org/gnome/Shell/Screenshot",
        "org.gnome.Shell.Screenshot",
        "Screenshot",
    )
    msg.setArguments([False, False, path])  # include_cursor, flash, filename
    reply = bus.call(msg)  # default mode is blocking
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        return None
    args = reply.arguments()
    if not args or not args[0]:
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    return _load(path)


def _capture_tool(argv):
    """Run an external capture tool writing to a file, return QImage or None."""
    if shutil.which(argv[0]) is None:
        return None
    fd, path = tempfile.mkstemp(suffix=".png", prefix="quicksnipp-")
    os.close(fd)
    try:
        subprocess.run(
            [*argv, path],
            check=True,
            timeout=15,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError):
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    return _load(path)


def _capture_grim():
    return _capture_tool(["grim"])


def _capture_gnome_screenshot():
    return _capture_tool(["gnome-screenshot", "-f"])


def _capture_spectacle():
    return _capture_tool(["spectacle", "--fullscreen", "--background", "--nonotify", "--output"])


def _capture_x11():
    """Stitch per-screen pixmaps into one virtual-desktop image (X11 only)."""
    app = QGuiApplication.instance()
    screens = app.screens()
    if not screens:
        return None
    virtual = screens[0].geometry()
    for s in screens[1:]:
        virtual = virtual.united(s.geometry())
    dpr = max(s.devicePixelRatio() for s in screens)
    img = QImage(int(virtual.width() * dpr), int(virtual.height() * dpr),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    for s in screens:
        pm = s.grabWindow(0)
        if pm.isNull():
            painter.end()
            return None
        target = s.geometry().translated(-virtual.topLeft())
        painter.drawPixmap(
            int(target.x() * dpr), int(target.y() * dpr),
            int(target.width() * dpr), int(target.height() * dpr),
            pm, 0, 0, pm.width(), pm.height(),
        )
    painter.end()
    return img


def _flatpak_app_id():
    """Our app-id when running inside a Flatpak sandbox, else None."""
    try:
        with open("/.flatpak-info", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("name="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return None


def capture_full_desktop() -> QImage:
    errors = []
    if _on_wayland():
        backends = (_capture_portal, _capture_gnome_shell, _capture_grim,
                    _capture_gnome_screenshot, _capture_spectacle)
    else:
        backends = (_capture_x11, _capture_spectacle, _capture_gnome_screenshot)
    for backend in backends:
        try:
            img = backend()
        except Exception as exc:  # noqa: BLE001 - collect and try next backend
            errors.append(f"{backend.__name__}: {exc}")
            continue
        if img is not None and not img.isNull():
            return img
    detail = "; ".join(errors) or "no working backend found"
    hint = ""
    app_id = _flatpak_app_id()
    if app_id and _on_wayland():
        # GNOME's portal rejects silent screenshots until the user grants
        # the screenshot permission once; tell them how.
        hint = (f"\n\nIf you just installed QuickSnipp, grant the screenshot "
                f"permission once, either in GNOME Settings → Apps → "
                f"{app_id} → Screenshots, or by running:\n"
                f"flatpak permission-set screenshot screenshot {app_id} yes")
    raise CaptureError(f"Could not capture the screen ({detail}){hint}")
