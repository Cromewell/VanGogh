#!/usr/bin/python3
import sys, os, random, json
from urllib.parse import quote
from io import BytesIO

import requests
from PIL import Image, ImageEnhance

from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QFileDialog, QMessageBox,
    QInputDialog, QFrame, QGraphicsView, QGraphicsScene,
    QLineEdit, QSizePolicy, QGraphicsPixmapItem,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QSize
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QFont,
    QTransform, QBrush, QShortcut, QKeySequence,
)

# ── Persistence ───────────────────────────────────────────────────────────────
_RECENT_FILE = os.path.expanduser("~/.vangogh_recent.json")

def _load_recent():
    try:
        with open(_RECENT_FILE) as f:
            return json.load(f)
    except Exception:
        return {"folders": [], "keywords": []}

def _save_recent(data):
    try:
        with open(_RECENT_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def _push_recent(data, key, value, limit=5):
    lst = data.setdefault(key, [])
    if value in lst:
        lst.remove(value)
    lst.insert(0, value)
    data[key] = lst[:limit]

# ── PIL → QPixmap ─────────────────────────────────────────────────────────────
def _to_pixmap(img: Image.Image) -> QPixmap:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    mode = img.mode
    data = img.tobytes()
    fmt  = QImage.Format_RGBA8888 if mode == "RGBA" else QImage.Format_RGB888
    bpl  = img.width * (4 if mode == "RGBA" else 3)
    return QPixmap.fromImage(QImage(data, img.width, img.height, bpl, fmt))

# ── Background image preloader ────────────────────────────────────────────────
class Preloader(QThread):
    done = Signal(str, object)   # (path, PIL Image | None)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            img = Image.open(self.path)
            img.load()
            self.done.emit(self.path, img)
        except Exception:
            self.done.emit(self.path, None)

# ── Circular countdown widget ─────────────────────────────────────────────────
class CircularTimer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(66, 66)
        self.seconds_left = 0
        self.initial_seconds = 0

    def update_state(self, seconds_left: int, initial_seconds: int):
        self.seconds_left = seconds_left
        self.initial_seconds = initial_seconds
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(6, 6, -6, -6)

        p.setPen(QPen(QColor("#333333"), 4))
        p.drawEllipse(r)

        frac = (self.seconds_left / self.initial_seconds
                if self.initial_seconds > 0 else 1.0)
        if frac > 0:
            pen = QPen(QColor("#4a9eff") if frac > 0.25 else QColor("#ff4444"), 4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-360 * frac * 16))

        p.setPen(QPen(QColor("#f0f0f0")))
        p.setFont(QFont("Arial", 11, QFont.Bold))
        m, s = divmod(self.seconds_left, 60)
        p.drawText(self.rect(), Qt.AlignCenter, f"{m:02d}:{s:02d}")

# ── Floating brightness / contrast panel ──────────────────────────────────────
class AdjustPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setFixedWidth(270)
        self.brightness = 1.0
        self.contrast   = 1.0
        self.setStyleSheet("""
            QWidget  { background:#1e1e1e; border-radius:8px; }
            QLabel   { background:transparent; }
            QPushButton { background:#2a2a2a; color:#888; border:none;
                          border-radius:4px; padding:4px; font-size:9px; }
            QPushButton:hover { background:#3a3a3a; color:#f0f0f0; }
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr = QLabel("Bildanpassungen")
        hdr.setStyleSheet("color:#888; font-size:10px; font-weight:bold;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#666; font-size:10px; padding:0; }"
            "QPushButton:hover { color:#f0f0f0; }"
        )
        close_btn.clicked.connect(self.hide)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        hdr_row.addWidget(close_btn)
        v.addLayout(hdr_row)

        self._b_slider, _ = self._row("Helligkeit", v)
        self._c_slider, _ = self._row("Kontrast",   v)

        rst = QPushButton("Zurücksetzen")
        rst.clicked.connect(self.reset)
        v.addWidget(rst)

    def _row(self, label: str, layout) -> tuple:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet("color:#f0f0f0; font-size:10px;")
        lbl.setFixedWidth(80)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 300)
        sl.setValue(100)
        val = QLabel("1.0")
        val.setStyleSheet("color:#888; font-size:9px;")
        val.setFixedWidth(26)
        sl.valueChanged.connect(lambda v, lv=val: lv.setText(f"{v/100:.1f}"))
        sl.valueChanged.connect(self._on_change)
        sl.mouseDoubleClickEvent = lambda e, s=sl: s.setValue(100)
        h.addWidget(lbl); h.addWidget(sl); h.addWidget(val)
        layout.addWidget(row)
        return sl, val

    def _on_change(self):
        self.brightness = self._b_slider.value() / 100
        self.contrast   = self._c_slider.value() / 100
        self.changed.emit()

    def reset(self):
        self._b_slider.setValue(100)
        self._c_slider.setValue(100)

    def toggle(self, anchor: QWidget):
        if self.isVisible():
            self.hide()
        else:
            gp  = anchor.mapToGlobal(anchor.rect().topRight())
            pos = QPoint(gp.x() - self.width() - 8, gp.y() + 4)
            self.move(pos)
            self.show()
            self.raise_()

# ── Image view (QGraphicsView — GPU zoom/pan) ─────────────────────────────────
class ImageView(QGraphicsView):
    scale_changed = Signal(float)
    mouse_moved   = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#111111")))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._pix)

        self._original_pil = None
        self._flipped      = False
        self._bw           = False
        self._brightness   = 1.0
        self._contrast     = 1.0
        self._fitted       = True
        self._fit_scale    = 1.0
        self._grid_on      = False
        self._grid_div     = 3
        self._grid_off_x   = 0.0
        self._grid_off_y   = 0.0
        self._grid_items   = []
        self._grid_pan_pos = None

        self._adjust_timer = QTimer(self)
        self._adjust_timer.setSingleShot(True)
        self._adjust_timer.setInterval(80)
        self._adjust_timer.timeout.connect(self._rebuild)

    # ── Loading ───────────────────────────────────────────────────────────────
    def load_pil(self, img: Image.Image):
        self._original_pil = img
        self._flipped = self._bw = False
        self._brightness = self._contrast = 1.0
        self._grid_off_x = self._grid_off_y = 0.0
        self._rebuild()
        self._scene.setSceneRect(self._pix.boundingRect())
        self.fit_image()

    def _rebuild(self):
        if self._original_pil is None:
            return
        img = self._original_pil
        if self._bw:
            img = img.convert("L")
        if self._brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(self._brightness)
        if self._contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(self._contrast)
        px = _to_pixmap(img)
        if self._flipped:
            px = px.transformed(QTransform().scale(-1, 1))
        self._pix.setPixmap(px)
        self._update_grid()

    # ── Adjustments ───────────────────────────────────────────────────────────
    def set_adjustments(self, brightness: float, contrast: float):
        self._brightness = brightness
        self._contrast   = contrast
        self._adjust_timer.start()  # restarts the 80 ms window on every tick

    def set_bw(self, on: bool):
        self._bw = on
        self._rebuild()

    def toggle_flip(self) -> bool:
        self._flipped = not self._flipped
        self._rebuild()
        return self._flipped

    def reset_view(self):
        self._flipped = self._bw = False
        self._brightness = self._contrast = 1.0
        self._grid_off_x = self._grid_off_y = 0.0
        self._rebuild()
        self.fit_image()

    # ── Fit / zoom ────────────────────────────────────────────────────────────
    def fit_image(self):
        self.fitInView(self._pix, Qt.KeepAspectRatio)
        self._fit_scale = self.transform().m11()
        self._fitted    = True
        self.scale_changed.emit(1.0)

    def _rel_scale(self) -> float:
        fs = self._fit_scale if self._fit_scale > 0 else 1.0
        return self.transform().m11() / fs

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fitted:
            self.fit_image()

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else 0.909
        self.scale(factor, factor)
        self._fitted = False
        self.scale_changed.emit(self._rel_scale())
        self._update_grid()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._fitted:
                self.scale(2.0, 2.0)
                self._fitted = False
                self._update_grid()
            else:
                self.fit_image()
            self.scale_changed.emit(self._rel_scale())
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        self.mouse_moved.emit()
        if self._grid_pan_pos is not None and (event.buttons() & Qt.RightButton):
            d  = event.pos() - self._grid_pan_pos
            iw = self._pix.pixmap().width()
            ih = self._pix.pixmap().height()
            sc = self.transform().m11()
            if iw and ih:
                self._grid_off_x = (self._grid_off_x + d.x() / (iw * sc)) % 1.0
                self._grid_off_y = (self._grid_off_y + d.y() / (ih * sc)) % 1.0
            self._grid_pan_pos = event.pos()
            self._update_grid()
        else:
            super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._grid_pan_pos = event.pos()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self._grid_pan_pos = None
        else:
            super().mouseReleaseEvent(event)

    # ── Grid ──────────────────────────────────────────────────────────────────
    def toggle_grid(self) -> bool:
        self._grid_on = not self._grid_on
        self._update_grid()
        return self._grid_on

    def change_grid_divisions(self, delta: int):
        self._grid_div = max(2, self._grid_div + delta)
        if self._grid_on:
            self._update_grid()

    def _update_grid(self):
        for item in self._grid_items:
            self._scene.removeItem(item)
        self._grid_items.clear()
        if not (self._grid_on and not self._pix.pixmap().isNull()):
            return
        iw = self._pix.pixmap().width()
        ih = self._pix.pixmap().height()
        pen = QPen(QColor(255, 255, 255, 160), 0)
        pen.setStyle(Qt.DashLine)
        pen.setCosmetic(True)
        for total, off, vertical in (
            (iw, self._grid_off_x, True),
            (ih, self._grid_off_y, False),
        ):
            step = total / self._grid_div
            curr = (off * total) % step
            while curr < total:
                if 1 < curr < total - 1:
                    if vertical:
                        item = self._scene.addLine(curr, 0, curr, ih, pen)
                    else:
                        item = self._scene.addLine(0, curr, iw, curr, pen)
                    item.setParentItem(self._pix)
                    self._grid_items.append(item)
                curr += step

# ── Session control pill (floating overlay) ───────────────────────────────────
class SessionPill(QWidget):
    sig_pause   = Signal()
    sig_next    = Signal()
    sig_flip    = Signal()
    sig_grid    = Signal()
    sig_bw      = Signal()
    sig_reset   = Signal()
    sig_adjust  = Signal()
    sig_help    = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            SessionPill { background:#252525; border-radius:12px; }
            QWidget      { background:transparent; }
            QPushButton {
                background:#363636; color:#c8c8c8; border:none;
                font-size:13px; height:32px; min-width:54px;
                border-radius:6px; padding:0 12px;
            }
            QPushButton:hover   { background:#484848; color:#ffffff; }
            QPushButton:checked { background:#1a3a5c; color:#4a9eff; }
            QPushButton#icon_btn {
                min-width:40px; max-width:40px; font-size:17px; padding:0;
            }
        """)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(6)

        self.timer_widget = CircularTimer()
        h.addWidget(self.timer_widget)
        h.addSpacing(4)
        self._sep()

        self.pause_btn = self._btn("⏸", self.sig_pause, icon=True)
        self._btn("⏭", self.sig_next, icon=True)
        self._sep()

        self.flip_btn = self._btn("Flip",   self.sig_flip, checkable=True)
        self.grid_btn = self._btn("Raster", self.sig_grid, checkable=True)
        self.bw_btn   = self._btn("S/W",    self.sig_bw,   checkable=True)
        self._sep()

        self._btn("Anpassen", self.sig_adjust)
        self._btn("Reset",    self.sig_reset)

    def _btn(self, text, sig=None, checkable=False, icon=False):
        b = QPushButton(text, self)
        b.setCheckable(checkable)
        if icon:
            b.setObjectName("icon_btn")
        if sig:
            b.clicked.connect(sig)
        self.layout().addWidget(b)
        return b

    def _sep(self):
        f = QFrame(self)
        f.setFrameShape(QFrame.VLine)
        f.setFixedSize(1, 20)
        f.setStyleSheet("background:#444; border:none;")
        self.layout().addSpacing(2)
        self.layout().addWidget(f)
        self.layout().addSpacing(2)

    def reposition(self, parent_w: int):
        self.adjustSize()
        self.move((parent_w - self.width()) // 2, 16)

# ── Drawing Session ───────────────────────────────────────────────────────────
class DrawingSession(QMainWindow):
    def __init__(self, image_data, seconds: int,
                 is_path=True, source=None, source_type=None):
        super().__init__()
        self.setWindowTitle("VanGogh")
        scr = QApplication.primaryScreen().size()
        self.resize(int(scr.width() * 0.85), int(scr.height() * 0.85))

        self.initial_seconds = seconds
        self.seconds_left    = seconds
        self.source          = source
        self.source_type     = source_type
        self._preloader      = None
        self._preloaded      = None
        self._paused         = False

        # Central view
        self.view = ImageView()
        self.setCentralWidget(self.view)
        self.view.mouse_moved.connect(self._on_mouse_moved)
        self.view.scale_changed.connect(self._show_zoom)

        # Pill (child of central widget so it floats above the view)
        self.pill = SessionPill(self.view)
        self.pill.sig_pause.connect(self.toggle_pause)
        self.pill.sig_next.connect(self.next_image)
        self.pill.sig_flip.connect(self._do_flip)
        self.pill.sig_grid.connect(self._do_grid)
        self.pill.sig_bw.connect(self._do_bw)
        self.pill.sig_reset.connect(self._do_reset)
        self.pill.sig_adjust.connect(lambda: self.adjust.toggle(self.pill))
        self.pill.sig_help.connect(self._show_help)
        self.pill.raise_()
        self.pill.enterEvent = lambda e: self._autohide.stop()
        self.pill.leaveEvent = lambda e: self._autohide.start()

        # Adjust panel
        self.adjust = AdjustPanel(self)
        self.adjust.changed.connect(lambda: self.view.set_adjustments(
            self.adjust.brightness, self.adjust.contrast))

        # Zoom label
        self._zoom_lbl = QLabel(self.view)
        self._zoom_lbl.setStyleSheet(
            "background:#000; color:#f0f0f0; padding:4px 9px;"
            "border-radius:4px; font-size:12px; font-weight:bold;")
        self._zoom_lbl.hide()
        self._zoom_timer = QTimer(singleShot=True)
        self._zoom_timer.timeout.connect(self._zoom_lbl.hide)

        # Time-up overlay
        self._timeup = QLabel(
            "Zeit abgelaufen\n\n"
            "N → Nächstes Bild     Space → Pause     T → Neu starten",
            self.view)
        self._timeup.setAlignment(Qt.AlignCenter)
        self._timeup.setStyleSheet(
            "background:rgba(0,0,0,210); color:#f0f0f0;"
            "font-size:16px; padding:40px;")
        self._timeup.hide()
        self._timeup_timer = QTimer(singleShot=True)
        self._timeup_timer.timeout.connect(self._timeup.hide)

        # Countdown
        self._tick_timer = QTimer()
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        # Auto-hide
        self._autohide = QTimer(singleShot=True)
        self._autohide.setInterval(3000)
        self._autohide.timeout.connect(self.pill.hide)

        self._setup_shortcuts()
        self._load(image_data, is_path)

        if seconds > 0:
            self.pill.timer_widget.update_state(seconds, seconds)
            self._tick_timer.start()
        else:
            self.pill.timer_widget.hide()
            self.pill.pause_btn.hide()

        self._preload_next()
        self._autohide.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        vw = self.view.width()
        vh = self.view.height()
        self.pill.reposition(vw)
        self._timeup.resize(vw, vh)
        if not self._zoom_lbl.isHidden():
            self._reposition_zoom_lbl()

    def _load(self, data, is_path: bool, pil=None):
        try:
            img = pil if pil is not None else (
                Image.open(data) if is_path else Image.open(BytesIO(data)))
            self.view.load_pil(img)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Bild konnte nicht geladen werden:\n{e}")

    # ── Shortcuts ─────────────────────────────────────────────────────────────
    def _setup_shortcuts(self):
        def s(key, fn):
            QShortcut(QKeySequence(key), self).activated.connect(fn)
        s("Space",   self.toggle_pause)
        s("N",       self.next_image)
        s("T",       self._do_restart)
        s("R",       self._do_reset)
        s("F",       self._do_flip)
        s("G",       self._do_grid)
        s("B",       self._do_bw)
        s("A",       lambda: self.adjust.toggle(self.pill))
        s("+",       lambda: self.view.change_grid_divisions(1))
        s("-",       lambda: self.view.change_grid_divisions(-1))
        s("H",       self._toggle_pill)
        s("F11",     self._toggle_fullscreen)
        s("F1",      self._show_help)
        s("Escape",  self.close)

    # ── Auto-hide ─────────────────────────────────────────────────────────────
    def _on_mouse_moved(self):
        if not self.pill.isVisible():
            self.pill.show()
            self.pill.raise_()
        self._autohide.start()

    def _toggle_pill(self):
        if self.pill.isVisible():
            self._autohide.stop()
            self.pill.hide()
        else:
            self.pill.show()
            self._autohide.start()

    # ── Zoom overlay ──────────────────────────────────────────────────────────
    def _show_zoom(self, rel_scale: float):
        self._zoom_lbl.setText(f"{int(rel_scale * 100)}%")
        self._zoom_lbl.adjustSize()
        self._reposition_zoom_lbl()
        self._zoom_lbl.show()
        self._zoom_lbl.raise_()
        self._zoom_timer.start(1500)

    def _reposition_zoom_lbl(self):
        vw = self.view.width()
        vh = self.view.height()
        self._zoom_lbl.move(vw - self._zoom_lbl.width() - 16,
                             vh - self._zoom_lbl.height() - 16)

    # ── Timer ─────────────────────────────────────────────────────────────────
    def _tick(self):
        if self.seconds_left > 0:
            self.seconds_left -= 1
            self.pill.timer_widget.update_state(self.seconds_left, self.initial_seconds)
        else:
            self._tick_timer.stop()
            self._timeup.resize(self.view.size())
            self._timeup.show()
            self._timeup.raise_()
            self._timeup_timer.start(4000)

    def toggle_pause(self):
        if self.initial_seconds <= 0:
            return
        self._paused = not self._paused
        self.pill.pause_btn.setText("▶" if self._paused else "⏸")
        if self._paused:
            self._tick_timer.stop()
        else:
            self._tick_timer.start()

    def _do_restart(self):
        if self.initial_seconds <= 0:
            return
        self._timeup.hide()
        self.seconds_left = self.initial_seconds
        self.pill.timer_widget.update_state(self.seconds_left, self.initial_seconds)
        self._tick_timer.start()

    # ── Actions ───────────────────────────────────────────────────────────────
    def _do_flip(self):
        on = self.view.toggle_flip()
        self.pill.flip_btn.setChecked(on)

    def _do_grid(self):
        on = self.view.toggle_grid()
        self.pill.grid_btn.setChecked(on)

    def _do_bw(self):
        on = not self.view._bw
        self.view.set_bw(on)
        self.pill.bw_btn.setChecked(on)

    def _do_reset(self):
        self.view.reset_view()
        self.pill.flip_btn.setChecked(False)
        self.pill.grid_btn.setChecked(False)
        self.pill.bw_btn.setChecked(False)
        self.adjust.reset()

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _show_help(self):
        QMessageBox.information(self, "VanGogh – Shortcuts",
            "Space\t: Pause / Resume\n"
            "T\t: Timer neu starten\n"
            "N\t: Nächstes Bild\n"
            "R\t: Ansicht zurücksetzen\n"
            "G\t: Raster an/aus\n"
            "+ / -\t: Raster-Dichte\n"
            "F\t: Spiegeln\n"
            "B\t: Schwarz/Weiß\n"
            "A\t: Anpassungen\n"
            "H\t: UI ein/ausblenden\n"
            "F11\t: Vollbild\n"
            "Esc\t: Beenden")

    # ── Preload / next ────────────────────────────────────────────────────────
    def _preload_next(self):
        if self.source_type != "local" or not self.source:
            return
        self._preloader = Preloader(random.choice(self.source))
        self._preloader.done.connect(lambda p, img: setattr(self, "_preloaded", (p, img)))
        self._preloader.start()

    def next_image(self):
        self._timeup.hide()
        if self.source_type == "local" and self.source:
            if self._preloaded:
                path, pil = self._preloaded
                self._preloaded = None
            else:
                path, pil = random.choice(self.source), None
            self._load(path, is_path=True, pil=pil)
            self._do_restart()
            self._preload_next()
        elif self.source_type == "web" and self.source:
            try:
                r = requests.get(
                    f"https://loremflickr.com/1920/1080/{quote(self.source)}",
                    timeout=10)
                r.raise_for_status()
                self._load(r.content, is_path=False)
                self._do_restart()
            except Exception as e:
                QMessageBox.critical(self, "Fehler",
                    f"Nächstes Bild konnte nicht geladen werden:\n{e}")

    def closeEvent(self, event):
        self._tick_timer.stop()
        self.adjust.hide()
        super().closeEvent(event)


# ── Main window ───────────────────────────────────────────────────────────────
_TIMER_OPTIONS = [
    ("Off", 0), ("30s", 30), ("1m", 60), ("2m", 120), ("3m", 180),
    ("5m", 300), ("10m", 600), ("15m", 900), ("30m", 1800), ("Custom", -1),
]

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VanGogh")
        self.setFixedSize(622, 520)
        self.timer_seconds = 0
        self._timer_btns   = {}
        self.recent        = _load_recent()
        self._build_ui()
        s = QApplication.primaryScreen().geometry()
        self.move((s.width() - self.width()) // 2, (s.height() - self.height()) // 2)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 25, 32, 18)
        root.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        t = QLabel("VanGogh")
        t.setStyleSheet("font-size:28px; font-weight:bold;")
        sub = QLabel("Drawing Sessions")
        sub.setStyleSheet("font-size:15px; color:#555; padding-top:6px; padding-left:10px;")
        hdr.addWidget(t); hdr.addWidget(sub); hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(16)
        root.addWidget(self._hdiv())
        root.addSpacing(14)

        # Timer chips
        lbl = QLabel("TIMER")
        lbl.setStyleSheet("font-size:13px; font-weight:bold; color:#555;")
        root.addWidget(lbl)
        chips = QHBoxLayout()
        chips.setSpacing(3)
        chips.setContentsMargins(0, 5, 0, 0)
        for label, secs in _TIMER_OPTIONS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _, s=secs, l=label: self._select_timer(s, l))
            chips.addWidget(b)
            self._timer_btns[label] = b
        chips.addStretch()
        root.addLayout(chips)
        self._timer_btns["Off"].setChecked(True)

        root.addSpacing(14)
        root.addWidget(self._hdiv())
        root.addSpacing(14)

        # Two columns
        cols = QHBoxLayout()
        cols.setSpacing(0)
        cols.addWidget(self._local_col())
        vd = QFrame(); vd.setFrameShape(QFrame.VLine)
        vd.setStyleSheet("color:#2a2a2a;"); vd.setContentsMargins(10,0,10,0)
        cols.addWidget(vd)
        cols.addWidget(self._web_col())
        root.addLayout(cols)
        root.addStretch()

        self.info_lbl = QLabel("")
        self.info_lbl.setAlignment(Qt.AlignCenter)
        self.info_lbl.setStyleSheet("font-size:14px; color:#555;")
        root.addWidget(self.info_lbl)

    def _local_col(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#1e1e1e; border-radius:6px;")
        v = QVBoxLayout(w); v.setContentsMargins(18,16,18,16); v.setSpacing(7)
        h = QLabel("Lokaler Ordner")
        h.setStyleSheet("font-size:16px; font-weight:bold; background:transparent;")
        s = QLabel("Referenzbilder vom Dateisystem")
        s.setStyleSheet("font-size:14px; color:#555; background:transparent;")
        b = QPushButton("Ordner wählen…")
        b.setObjectName("accent_blue"); b.clicked.connect(self.open_local)
        self._rf = QVBoxLayout()
        self._rf.setSpacing(2)
        v.addWidget(h); v.addWidget(s); v.addWidget(b)
        v.addLayout(self._rf); v.addStretch()
        self._refresh_folders()
        return w

    def _web_col(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#1e1e1e; border-radius:6px;")
        v = QVBoxLayout(w); v.setContentsMargins(18,16,18,16); v.setSpacing(7)
        h = QLabel("Web-Suche")
        h.setStyleSheet("font-size:16px; font-weight:bold; background:transparent;")
        s = QLabel("loremflickr.com")
        s.setStyleSheet("font-size:14px; color:#555; background:transparent;")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchbegriff…")
        self.search.returnPressed.connect(self.open_web)
        b = QPushButton("Suchen")
        b.setObjectName("accent_orange"); b.clicked.connect(self.open_web)
        self._rk = QVBoxLayout()
        self._rk.setSpacing(2)
        v.addWidget(h); v.addWidget(s); v.addWidget(self.search); v.addWidget(b)
        v.addLayout(self._rk); v.addStretch()
        self._refresh_keywords()
        return w

    def _hdiv(self) -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#2a2a2a;"); return f

    def _select_timer(self, seconds: int, label: str):
        if label == "Custom":
            mins, ok = QInputDialog.getInt(self, "Timer", "Minuten:", 5, 1, 999)
            if not ok:
                self._timer_btns["Custom"].setChecked(False); return
            seconds = mins * 60
        for b in self._timer_btns.values():
            b.setChecked(False)
        (self._timer_btns.get(label) or self._timer_btns["Custom"]).setChecked(True)
        self.timer_seconds = seconds

    def _info(self, text: str, error=False):
        self.info_lbl.setText(text)
        self.info_lbl.setStyleSheet(
            f"font-size:14px; color:{'#ff4444' if error else '#555'};")

    def _refresh_folders(self):
        while self._rf.count():
            w = self._rf.takeAt(0).widget()
            if w: w.deleteLater()
        for folder in self.recent.get("folders", []):
            b = QPushButton(f"↩  {os.path.basename(folder) or folder}")
            b.setStyleSheet("font-size:12px; color:#555; text-align:left; padding:2px 4px;")
            b.clicked.connect(lambda _, f=folder: self._open_folder(f))
            self._rf.addWidget(b)

    def _refresh_keywords(self):
        while self._rk.count():
            w = self._rk.takeAt(0).widget()
            if w: w.deleteLater()
        for kw in self.recent.get("keywords", []):
            b = QPushButton(f"↩  {kw}")
            b.setStyleSheet("font-size:12px; color:#555; text-align:left; padding:2px 4px;")
            b.clicked.connect(lambda _, k=kw: self._start_web(k))
            self._rk.addWidget(b)

    def open_local(self):
        default = (self.recent.get("folders") or [os.path.expanduser("~/Pictures")])[0]
        folder = QFileDialog.getExistingDirectory(self, "Ordner wählen", default)
        if folder:
            self._open_folder(folder)

    def _open_folder(self, folder: str):
        exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
        paths = [os.path.join(dp, f)
                 for dp, _, files in os.walk(folder)
                 for f in files if f.lower().endswith(exts)]
        if not paths:
            self._info("Keine Bilder gefunden.", error=True); return
        _push_recent(self.recent, "folders", folder)
        _save_recent(self.recent)
        self._refresh_folders()
        selected = random.choice(paths)
        self._info(f"{len(paths)} Bilder · {os.path.basename(selected)}")
        DrawingSession(selected, self.timer_seconds,
                       is_path=True, source=paths, source_type="local").show()

    def open_web(self):
        kw = self.search.text().strip()
        if not kw:
            self._info("Bitte Suchbegriff eingeben.", error=True); return
        self._start_web(kw)

    def _start_web(self, keyword: str):
        self.search.setText(keyword)
        self._info("Lade Bild …")
        QApplication.processEvents()
        try:
            r = requests.get(
                f"https://loremflickr.com/1920/1080/{quote(keyword)}", timeout=10)
            r.raise_for_status()
            _push_recent(self.recent, "keywords", keyword)
            _save_recent(self.recent)
            self._refresh_keywords()
            self._info(f"'{keyword}' geladen.")
            DrawingSession(r.content, self.timer_seconds,
                           is_path=False, source=keyword, source_type="web").show()
        except Exception as e:
            self._info(f"Fehler: {e}", error=True)


# ── Global stylesheet ─────────────────────────────────────────────────────────
_STYLE = """
QWidget { background:#111111; color:#f0f0f0;
          font-family:"Helvetica Neue","Helvetica","Arial","Segoe UI",sans-serif; }
QPushButton { background:#2a2a2a; color:#aaa; border:none;
              border-radius:4px; padding:5px 10px; font-size:15px; }
QPushButton:hover   { background:#3a3a3a; color:#f0f0f0; }
QPushButton:checked { background:#1a3a5c; color:#4a9eff; }
QPushButton#accent_blue   { background:#4a9eff; color:#fff;
                             font-weight:bold; padding:8px; }
QPushButton#accent_blue:hover  { background:#3a8ef0; }
QPushButton#accent_orange { background:#ff6b35; color:#fff;
                             font-weight:bold; padding:8px; }
QPushButton#accent_orange:hover { background:#ef5b25; }
QLineEdit { background:#2a2a2a; border:1px solid #3a3a3a;
            border-radius:4px; padding:6px; font-size:15px; }
QLineEdit:focus { border-color:#4a9eff; }
QSlider::groove:horizontal { background:#2a2a2a; height:4px; border-radius:2px; }
QSlider::handle:horizontal { background:#4a9eff; width:12px; height:12px;
                              margin:-4px 0; border-radius:6px; }
QSlider::sub-page:horizontal { background:#4a9eff; border-radius:2px; }
"""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(_STYLE)
    w = App()
    w.show()
    sys.exit(app.exec())
