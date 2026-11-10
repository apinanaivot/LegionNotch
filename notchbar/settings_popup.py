"""The small settings panel opened by the gear in the expanded bar."""
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QRectF, Qt

from .config import ACCENT, DIM, THEMES, TXT
from .winapi import is_installed, startup_enabled, uninstall_self

FONT = "Segoe UI Variable Text"


class Switch(QtWidgets.QAbstractButton):
    """Small on/off switch, drawn by hand so it matches the bar."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 16)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        p.setBrush(ACCENT if on else QtGui.QColor(255, 255, 255, 18))
        p.setPen(Qt.NoPen if on else QtGui.QPen(QtGui.QColor(255, 255, 255, 60), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - 3 - d if on else r.left() + 3
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 255, 255) if on else QtGui.QColor(190, 194, 202))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class Row(QtWidgets.QWidget):
    toggled = QtCore.Signal(bool)

    def __init__(self, label, hint):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        a = QtWidgets.QLabel(label)
        a.setStyleSheet(f"color:{TXT.name()};font:10pt '{FONT}'")
        text.addWidget(a)
        if hint:
            b = QtWidgets.QLabel(hint)
            b.setStyleSheet(f"color:{DIM.name()};font:8pt '{FONT}'")
            text.addWidget(b)
        lay.addLayout(text, 1)
        self.switch = Switch()
        self.switch.toggled.connect(self.toggled)
        lay.addWidget(self.switch, 0, Qt.AlignVCenter)

    def mousePressEvent(self, e):
        self.switch.toggle()


class ThemePicker(QtWidgets.QWidget):
    """Row of colour swatches, one per theme."""
    picked = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.names = list(THEMES)
        self.current = self.names[0]
        self.setFixedHeight(26)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QtCore.QSize(120, 26)

    def _rect(self, i):
        return QRectF(self.width() - (len(self.names) - i) * 26 + 2, 3, 20, 20)

    def set_current(self, name):
        self.current = name if name in THEMES else self.names[0]
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(DIM)
        p.setFont(QtGui.QFont(FONT, 10))
        p.drawText(QRectF(0, 0, self.width() - 90, self.height()), Qt.AlignVCenter | Qt.AlignLeft, "Theme")
        for i, n in enumerate(self.names):
            r = self._rect(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(*THEMES[n][0]))
            p.drawEllipse(r.adjusted(4, 4, -4, -4))
            if n == self.current:
                p.setBrush(Qt.NoBrush)
                p.setPen(QtGui.QPen(TXT, 1.5))
                p.drawEllipse(r.adjusted(1, 1, -1, -1))

    def mousePressEvent(self, e):
        for i, n in enumerate(self.names):
            if self._rect(i).contains(e.position()):
                self.set_current(n)
                self.picked.emit(n)

    def mouseMoveEvent(self, e):
        hit = [n for i, n in enumerate(self.names) if self._rect(i).contains(e.position())]
        self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        self.setToolTip(hit[0] if hit else "")


class SettingsPopup(QtWidgets.QFrame):
    ROWS = (("mode_color", "Colour the power mode", "Off uses the theme colour"),
            ("auto_hide", "Auto-hide", "Shows when the mouse is at the top centre"),
            ("startup", "Start with Windows", ""),
            ("pinned", "Keep expanded", ""),
            ("show_temps", "Show temperatures", ""),
            ("gpu_power", "Show GPU power draw", ""),
            ("task_manager_click", "Open Task Manager on click", ""))

    def __init__(self, bar):
        super().__init__(bar, Qt.Popup | Qt.FramelessWindowHint)
        self.bar = bar
        self.setStyleSheet("SettingsPopup{background:#101113;border:1px solid #2a2c31;border-radius:8px}")
        self.setMinimumWidth(290)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(11)
        title = QtWidgets.QLabel("Settings")
        title.setStyleSheet(f"color:{TXT.name()};font:600 11pt '{FONT}'")
        lay.addWidget(title)
        self.theme = ThemePicker()
        self.theme.picked.connect(lambda n: bar.apply_setting("theme", n))
        lay.addWidget(self.theme)
        self.rows = {}
        for key, label, hint in self.ROWS:
            row = Row(label, hint)
            row.toggled.connect(lambda on, k=key: bar.apply_setting(k, on))
            lay.addWidget(row)
            self.rows[key] = row
        if is_installed():
            line = QtWidgets.QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet("background:#2a2c31")
            lay.addWidget(line)
            btn = QtWidgets.QPushButton("Uninstall LegionNotch…")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"QPushButton{{color:{DIM.name()};font:10pt '{FONT}';border:none;text-align:left;padding:0}}"
                              f"QPushButton:hover{{color:#e4262f}}")
            btn.clicked.connect(self._uninstall)
            lay.addWidget(btn)
        self.adjustSize()

    def _uninstall(self):
        self.hide()
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Uninstall LegionNotch",
                                    "Remove LegionNotch, its settings, Start menu shortcut and startup entry?")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        box.button(QtWidgets.QMessageBox.Yes).setText("Uninstall")
        if box.exec() == QtWidgets.QMessageBox.Yes:
            uninstall_self()
            QtWidgets.QApplication.quit()

    def popup_at(self, right_bottom):
        cur = dict(self.bar.cfg, startup=startup_enabled(), pinned=self.bar.pinned)
        self.theme.set_current(self.bar.cfg["theme"])
        for k, row in self.rows.items():
            row.switch.blockSignals(True)
            row.switch.setChecked(bool(cur.get(k)))
            row.switch.blockSignals(False)
        self.adjustSize()
        self.move(right_bottom.x() - self.width(), right_bottom.y() + 4)
        self.bar.popup_open = True
        self.show()

    def hideEvent(self, e):
        self.bar.popup_open = False
        self.bar.after_popup()
        super().hideEvent(e)
