"""Screen capture backends for Wayland (GNOME/wlroots/KDE) and X11.

capture_full_desktop() returns a QImage covering the whole virtual desktop
(all monitors stitched together) or raises CaptureError.
"""

import os
import shutil
import subprocess
import tempfile

from PyQt6.QtCore import QEventLoop, QObject, QRect, QTimer, QUrl, pyqtSlot
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage, QDBusVariant
from PyQt6.QtGui import QGuiApplication, QImage, QPainter


class CaptureError(RuntimeError):
    pass


def _on_wayland() -> bool:
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.exists(os.path.join(runtime, "wayland-0"))


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
        self.code: int | None = None
        self.done = False

    @pyqtSlot("QDBusMessage")
    def on_response(self, message):
        if self.request_path and message.path() != self.request_path:
            return  # another app's portal request
        args = message.arguments()
        if args:
            try:
                self.code = int(args[0])
            except (TypeError, ValueError):
                self.code = None
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
    if reply.type() == QDBusMessage.MessageType.ErrorMessage or not reply.arguments():
        bus.disconnect(None, None, "org.freedesktop.portal.Request",
                       "Response", handler.on_response)
        err = reply.errorMessage() or reply.errorName() or "empty reply"
        raise CaptureError(err)

    handler.request_path = str(reply.arguments()[0])
    QTimer.singleShot(20000, handler.loop.quit)  # safety timeout
    handler.loop.exec()
    bus.disconnect(None, None, "org.freedesktop.portal.Request",
                   "Response", handler.on_response)
    if not handler.done:
        raise CaptureError("screenshot portal timed out")
    if not handler.uri:
        raise CaptureError(
            f"screenshot portal returned no image (code={handler.code})")
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
        raise CaptureError(reply.errorMessage() or reply.errorName())
    args = reply.arguments()
    if not args or not args[0]:
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    return _load(path)


def _virtual_desktop() -> QRect | None:
    app = QGuiApplication.instance()
    screens = app.screens() if app is not None else []
    if not screens:
        return None
    virt = screens[0].geometry()
    for s in screens[1:]:
        virt = virt.united(s.geometry())
    return virt


def _capture_mutter():
    """One still frame via Mutter ScreenCast + GStreamer.

    GNOME 47+ blocks org.gnome.Shell.Screenshot and silent portal shots
    ("Screenshot is not allowed" / portal code 2). ScreenCast is already
    allowed for QuickSnipp video, so a single PipeWire frame works.
    """
    if shutil.which("gst-launch-1.0") is None:
        return None
    virt = _virtual_desktop()
    if virt is None or virt.width() < 2 or virt.height() < 2:
        return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None

    def call(dest, path, iface, method, args, timeout=15000):
        msg = QDBusMessage.createMethodCall(dest, path, iface, method)
        msg.setArguments(args)
        return bus.call(msg, QDBus.CallMode.Block, timeout)

    reply = call(
        "org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast",
        "org.gnome.Mutter.ScreenCast", "CreateSession", [{}])
    if reply.type() == QDBusMessage.MessageType.ErrorMessage or not reply.arguments():
        err = reply.errorName() or ""
        if "ServiceUnknown" in err or "NameHasNoOwner" in err:
            return None
        raise CaptureError(reply.errorMessage() or err or "CreateSession failed")
    session_path = str(reply.arguments()[0])

    def stop():
        call("org.gnome.Mutter.ScreenCast", session_path,
             "org.gnome.Mutter.ScreenCast.Session", "Stop", [], timeout=5000)

    w = virt.width() - (virt.width() % 2)
    h = virt.height() - (virt.height() % 2)
    opts = {
        "is-recording": QDBusVariant(True),
        "cursor-mode": QDBusVariant(1),
    }
    reply = call(
        "org.gnome.Mutter.ScreenCast", session_path,
        "org.gnome.Mutter.ScreenCast.Session", "RecordArea",
        [int(virt.x()), int(virt.y()), int(w), int(h), opts])
    if reply.type() == QDBusMessage.MessageType.ErrorMessage or not reply.arguments():
        stop()
        raise CaptureError(reply.errorMessage() or "RecordArea failed")
    stream_path = str(reply.arguments()[0])

    class _PwHandler(QObject):
        def __init__(self):
            super().__init__()
            self.node = None
            self.loop = QEventLoop()

        @pyqtSlot("QDBusMessage")
        def on_stream(self, message):
            args = message.arguments()
            if args:
                self.node = args[0]
            if self.loop.isRunning():
                self.loop.quit()

    handler = _PwHandler()
    if not bus.connect(None, stream_path, "org.gnome.Mutter.ScreenCast.Stream",
                       "PipeWireStreamAdded", handler.on_stream):
        stop()
        raise CaptureError("could not subscribe to PipeWireStreamAdded")
    reply = call(
        "org.gnome.Mutter.ScreenCast", session_path,
        "org.gnome.Mutter.ScreenCast.Session", "Start", [])
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        bus.disconnect(None, stream_path, "org.gnome.Mutter.ScreenCast.Stream",
                       "PipeWireStreamAdded", handler.on_stream)
        stop()
        raise CaptureError(reply.errorMessage() or "ScreenCast Start failed")
    if handler.node is None:
        QTimer.singleShot(8000, handler.loop.quit)
        handler.loop.exec()
    bus.disconnect(None, stream_path, "org.gnome.Mutter.ScreenCast.Stream",
                   "PipeWireStreamAdded", handler.on_stream)
    if handler.node is None:
        stop()
        raise CaptureError("no PipeWire stream (timed out)")

    fd, path = tempfile.mkstemp(suffix=".png", prefix="quicksnipp-")
    os.close(fd)
    cmd = [
        "gst-launch-1.0", "-q",
        "pipewiresrc", f"path={handler.node}",
        "num-buffers=1", "do-timestamp=true",
        "keepalive-time=1000", "resend-last=true",
        "!", "videoconvert",
        "!", "pngenc",
        "!", "filesink", f"location={path}",
    ]
    try:
        proc = subprocess.run(
            cmd, check=False, timeout=8,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (subprocess.SubprocessError, OSError) as exc:
        stop()
        try:
            os.unlink(path)
        except OSError:
            pass
        raise CaptureError(str(exc)) from exc
    stop()
    if proc.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) < 32:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        try:
            os.unlink(path)
        except OSError:
            pass
        raise CaptureError(detail or f"gst-launch exit {proc.returncode}")
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
        backends = (_capture_portal, _capture_gnome_shell, _capture_mutter,
                    _capture_grim, _capture_gnome_screenshot, _capture_spectacle,
                    _capture_x11)
    else:
        backends = (_capture_portal, _capture_x11, _capture_spectacle,
                    _capture_gnome_screenshot, _capture_gnome_shell,
                    _capture_mutter)
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
