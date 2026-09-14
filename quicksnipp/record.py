"""Region video recording backends (GNOME / wf-recorder / ffmpeg x11grab)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

from PyQt6.QtCore import (QEventLoop, QObject, QPoint, QRect, Qt, QTimer,
                          pyqtSignal, pyqtSlot)
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage, QDBusVariant
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class RecordError(RuntimeError):
    pass


class RecordingSession:
    """Active recording that can be stopped; stop() returns the output path."""

    def stop(self) -> str:
        raise NotImplementedError


def even_rect(rect: QRect) -> QRect:
    """H.264/VP8 need even dimensions; shrink width/height if odd."""
    w = rect.width() - (rect.width() % 2)
    h = rect.height() - (rect.height() % 2)
    if w < 2 or h < 2:
        raise RecordError("Selected area is too small to record")
    return QRect(rect.x(), rect.y(), w, h)


def _videos_dir() -> str:
    try:
        out = subprocess.check_output(
            ["xdg-user-dir", "VIDEOS"], text=True, timeout=2).strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.expanduser("~/Videos")


def _default_path(ext: str, output_path: str | None = None) -> str:
    if output_path:
        root, given_ext = os.path.splitext(output_path)
        if not given_ext:
            return output_path + f".{ext}"
        return output_path
    folder = _videos_dir()
    os.makedirs(folder, exist_ok=True)
    base = time.strftime("snipp-%Y%m%d-%H%M%S")
    path = os.path.join(folder, f"{base}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base}-{n}.{ext}")
        n += 1
    return path


def _on_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _is_gnome() -> bool:
    return "gnome" in (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()


def _dbus_call(bus, dest, path, iface, method, args, timeout=15000):
    msg = QDBusMessage.createMethodCall(dest, path, iface, method)
    msg.setArguments(args)
    return bus.call(msg, QDBus.CallMode.Block, timeout)


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


class _ProcessRecordingSession(RecordingSession):
    def __init__(self, proc: subprocess.Popen, path: str, mutter_session: str | None = None):
        self._proc = proc
        self._path = path
        self._mutter_session = mutter_session
        self._stopped = False

    def stop(self) -> str:
        if self._stopped:
            return self._path
        self._stopped = True
        _stop_process(self._proc)
        if self._mutter_session:
            _mutter_stop(self._mutter_session)
        return self._path


def _mutter_stop(session_path: str) -> None:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return
    _dbus_call(bus, "org.gnome.Mutter.ScreenCast", session_path,
               "org.gnome.Mutter.ScreenCast.Session", "Stop", [], timeout=5000)


def _start_mutter_gst(rect: QRect, output_path: str | None,
                      errors: list[str]) -> RecordingSession | None:
    """GNOME/Mutter region stream + gst-launch (works when the Shell helper cannot)."""
    if shutil.which("gst-launch-1.0") is None:
        errors.append("mutter-gst: gst-launch-1.0 not found")
        return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        errors.append("mutter-gst: no session bus")
        return None

    reply = _dbus_call(
        bus, "org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast",
        "org.gnome.Mutter.ScreenCast", "CreateSession", [{}])
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        err = reply.errorName() or ""
        if "ServiceUnknown" in err or "NameHasNoOwner" in err:
            return None  # not GNOME
        errors.append(f"mutter-gst CreateSession: {reply.errorMessage() or err}")
        return None
    if not reply.arguments():
        errors.append("mutter-gst: CreateSession returned no path")
        return None
    session_path = str(reply.arguments()[0])

    def fail(msg: str):
        errors.append(msg)
        _mutter_stop(session_path)
        return None

    opts = {
        "is-recording": QDBusVariant(True),
        "cursor-mode": QDBusVariant(1),
    }
    reply = _dbus_call(
        bus, "org.gnome.Mutter.ScreenCast", session_path,
        "org.gnome.Mutter.ScreenCast.Session", "RecordArea",
        [int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()), opts])
    if reply.type() == QDBusMessage.MessageType.ErrorMessage or not reply.arguments():
        return fail(f"mutter-gst RecordArea: {reply.errorMessage() or 'failed'}")
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
        return fail("mutter-gst: could not subscribe to PipeWireStreamAdded")

    reply = _dbus_call(
        bus, "org.gnome.Mutter.ScreenCast", session_path,
        "org.gnome.Mutter.ScreenCast.Session", "Start", [])
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        bus.disconnect(None, stream_path, "org.gnome.Mutter.ScreenCast.Stream",
                       "PipeWireStreamAdded", handler.on_stream)
        return fail(f"mutter-gst Start: {reply.errorMessage()}")

    if handler.node is None:
        QTimer.singleShot(8000, handler.loop.quit)
        handler.loop.exec()
    bus.disconnect(None, stream_path, "org.gnome.Mutter.ScreenCast.Stream",
                   "PipeWireStreamAdded", handler.on_stream)
    if handler.node is None:
        return fail("mutter-gst: no PipeWire stream (timed out)")

    path = _default_path("webm", output_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    cmd = [
        "gst-launch-1.0", "-e", "-q",
        "pipewiresrc", f"path={handler.node}",
        "do-timestamp=true", "keepalive-time=1000", "resend-last=true",
        "!", "videoconvert",
        "!", "queue",
        "!", "vp8enc", "deadline=1", "cpu-used=16", "max-quantizer=17",
        "!", "webmmux",
        "!", "filesink", f"location={path}",
    ]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:
        return fail(f"mutter-gst: {exc}")
    try:
        _, err = proc.communicate(timeout=0.5)
    except subprocess.TimeoutExpired:
        return _ProcessRecordingSession(proc, path, mutter_session=session_path)
    detail = (err or b"").decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
    return fail(f"mutter-gst encoder: {detail}")


def _start_gnome_shell(rect: QRect, output_path: str | None,
                       errors: list[str]) -> RecordingSession | None:
    """Older/alternate GNOME helper (often fails on GNOME 50 DMA-BUF)."""
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    # GNOME appends the container extension itself; strip .webm if present.
    path = _default_path("webm", output_path)
    stem, ext = os.path.splitext(path)
    if ext.lower() == ".webm":
        path = stem
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    msg = QDBusMessage.createMethodCall(
        "org.gnome.Shell.Screencast",
        "/org/gnome/Shell/Screencast",
        "org.gnome.Shell.Screencast",
        "ScreencastArea",
    )
    options = {
        "framerate": QDBusVariant(30),
        "draw-cursor": QDBusVariant(True),
        "pipeline": QDBusVariant(
            "videoconvert chroma-mode=none dither=none ! "
            "queue ! vp8enc cpu-used=16 max-quantizer=17 deadline=1 ! webmmux"
        ),
    }
    msg.setArguments([
        int(rect.x()), int(rect.y()),
        int(rect.width()), int(rect.height()),
        path,
        options,
    ])
    reply = bus.call(msg, QDBus.CallMode.Block, 30000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        err = reply.errorName() or ""
        if "ServiceUnknown" in err or "NameHasNoOwner" in err:
            return None
        errors.append(f"gnome-shell: {reply.errorMessage() or err}")
        return None
    args = reply.arguments()
    if not args or not args[0]:
        errors.append("gnome-shell: ScreencastArea returned failure")
        return None
    used = str(args[1]) if len(args) > 1 and args[1] else path
    # Stop via the shell helper; wrap as a process-less session.
    return _GnomeShellSession(used)


class _GnomeShellSession(RecordingSession):
    def __init__(self, path: str):
        self._path = path
        self._stopped = False

    def stop(self) -> str:
        if self._stopped:
            return self._path
        self._stopped = True
        bus = QDBusConnection.sessionBus()
        if bus.isConnected():
            _dbus_call(bus, "org.gnome.Shell.Screencast",
                       "/org/gnome/Shell/Screencast",
                       "org.gnome.Shell.Screencast", "StopScreencast", [],
                       timeout=10000)
        return self._path


def _start_process(cmd: list[str], path: str,
                   errors: list[str], label: str) -> RecordingSession | None:
    if shutil.which(cmd[0]) is None:
        return None
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        errors.append(f"{label}: {exc}")
        return None
    try:
        _, err = proc.communicate(timeout=0.4)
    except subprocess.TimeoutExpired:
        return _ProcessRecordingSession(proc, path)
    detail = (err or b"").decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
    errors.append(f"{label}: {detail}")
    return None


def _start_wf_recorder(rect: QRect, output_path: str | None,
                       errors: list[str]) -> RecordingSession | None:
    path = _default_path("mp4", output_path)
    geom = f"{rect.x()},{rect.y()} {rect.width()}x{rect.height()}"
    return _start_process(
        ["wf-recorder", "-g", geom, "-f", path], path, errors, "wf-recorder")


def _start_ffmpeg_x11(rect: QRect, output_path: str | None,
                      errors: list[str]) -> RecordingSession | None:
    if _on_wayland():
        return None
    if shutil.which("ffmpeg") is None:
        return None
    display = os.environ.get("DISPLAY") or ":0"
    app = QGuiApplication.instance()
    dpr = 1.0
    if app is not None:
        screens = app.screens()
        if screens:
            dpr = max(s.devicePixelRatio() for s in screens)
    if abs(dpr - 1.0) > 0.01:
        rect = even_rect(QRect(
            int(rect.x() * dpr), int(rect.y() * dpr),
            int(rect.width() * dpr), int(rect.height() * dpr),
        ))
    path = _default_path("mp4", output_path)
    grab = f"{display}+{rect.x()},{rect.y()}"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y", "-nostdin",
        "-f", "x11grab",
        "-video_size", f"{rect.width()}x{rect.height()}",
        "-framerate", "30",
        "-i", grab,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        path,
    ]
    return _start_process(cmd, path, errors, "ffmpeg")


def start_region_recording(rect: QRect, output_path: str | None = None) -> RecordingSession:
    """Start recording `rect` (virtual logical coords) to a file under ~/Videos."""
    rect = even_rect(rect)
    errors: list[str] = []
    if _is_gnome():
        backends = (_start_mutter_gst, _start_gnome_shell, _start_wf_recorder,
                    _start_ffmpeg_x11)
    else:
        # Raspberry Pi OS / Sway / Hyprland: wf-recorder talks to the compositor.
        backends = (_start_wf_recorder, _start_mutter_gst, _start_gnome_shell,
                    _start_ffmpeg_x11)
    for backend in backends:
        try:
            session = backend(rect, output_path, errors)
        except RecordError:
            raise
        except Exception as exc:  # noqa: BLE001 - try the next backend
            errors.append(f"{backend.__name__}: {exc}")
            continue
        if session is not None:
            return session
    detail = "; ".join(errors) or "no working backend found"
    hint = ""
    if _on_wayland():
        hint = ("\n\nOn GNOME, screen recording must be allowed if prompted. "
                "On Raspberry Pi OS / Sway / labwc, install wf-recorder:\n"
                "  sudo apt install wf-recorder grim")
    raise RecordError(f"Could not start region recording ({detail}){hint}")


class RecordingBar(QWidget):
    """Always-on-top timer + Stop control, placed outside the recorded region."""

    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setWindowTitle("QuickSnipp Recording")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._started = time.monotonic()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        dot = QLabel("●")
        dot.setStyleSheet("color: #ff3b30; font-size: 16px; font-weight: bold;")
        layout.addWidget(dot)

        rec = QLabel("REC")
        rec.setStyleSheet("color: #ff3b30; font-weight: bold; font-size: 13px;")
        layout.addWidget(rec)

        self._time = QLabel("00:00")
        self._time.setStyleSheet(
            "color: #e6e6e6; font-weight: bold; font-size: 14px; padding: 0 6px;")
        layout.addWidget(self._time)

        stop = QPushButton("Stop")
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.setFixedHeight(30)
        stop.clicked.connect(self.stop_requested.emit)
        layout.addWidget(stop)

        self.setStyleSheet("""
            RecordingBar {
                background: #1b1e23;
                color: #e6e6e6;
                border: 1px solid #3a4048;
                border-radius: 10px;
            }
            QPushButton {
                background: #c62828;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background: #e53935; }
        """)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)

    def _tick(self):
        elapsed = int(time.monotonic() - self._started)
        self._time.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.stop_requested.emit()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_requested.emit()
        super().closeEvent(event)

    def place_outside(self, region: QRect):
        self.adjustSize()
        screens = QGuiApplication.screens()
        if not screens:
            return
        virtual = screens[0].geometry()
        for s in screens[1:]:
            virtual = virtual.united(s.geometry())
        w, h = self.width(), self.height()

        def clamp(p: QPoint) -> QPoint:
            x = min(max(p.x(), virtual.left() + 8), max(virtual.left() + 8, virtual.right() - w - 8))
            y = min(max(p.y(), virtual.top() + 8), max(virtual.top() + 8, virtual.bottom() - h - 8))
            return QPoint(x, y)

        def overlaps(p: QPoint) -> bool:
            return QRect(p.x(), p.y(), w, h).intersects(region)

        candidates = [
            QPoint(region.center().x() - w // 2, region.top() - h - 12),
            QPoint(region.center().x() - w // 2, region.bottom() + 12),
            QPoint(region.left(), region.top() - h - 12),
            QPoint(virtual.right() - w - 16, virtual.top() + 16),
            QPoint(virtual.left() + 16, virtual.top() + 16),
        ]
        chosen = None
        for raw in candidates:
            p = clamp(raw)
            if not overlaps(p):
                chosen = p
                break
        if chosen is None:
            chosen = clamp(candidates[-1])
        self.move(chosen)
