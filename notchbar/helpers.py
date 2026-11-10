"""Formatting, fonts, shape helpers and the calm-text state used by the painter."""
from PySide6 import QtCore, QtGui
from PySide6.QtCore import QPointF

from .config import C_HOT, C_WARN, DIM, SMOOTHING


def fmt_rate(b):
    """Byte rate with explicit units: 0.2 KB/s, 84 KB/s, 1.2 MB/s, 12 MB/s ..."""
    b /= 1024
    for unit in ("KB/s", "MB/s", "GB/s"):
        if b < 1000 or unit == "GB/s":
            return f"{b:.1f} {unit}" if b < 10 else f"{b:.0f} {unit}"
        b /= 1024
    return "?"


def temp_color(t):
    if t is None:
        return DIM
    if t >= 85:
        return C_HOT
    if t >= 70:
        return C_WARN
    return DIM


def font(px, weight=QtGui.QFont.Weight.Normal):
    f = QtGui.QFont("Segoe UI Variable Text")
    f.setPixelSize(px)
    f.setWeight(weight)
    try:  # tabular figures so numbers don't jiggle (Qt >= 6.7)
        f.setFeature(QtGui.QFont.Tag("tnum"), 1)
    except Exception:
        pass
    return f


def rounded_polygon(pts):
    """Closed path through (x, y, radius) vertices, each corner rounded by its radius
    (clamped so neighbouring roundings never overlap)."""
    path = QtGui.QPainterPath()
    n = len(pts)
    for i, (x, y, r) in enumerate(pts):
        v = QPointF(x, y)
        if r <= 0:
            path.moveTo(v) if i == 0 else path.lineTo(v)
            continue
        pv, nv = QPointF(*pts[i - 1][:2]), QPointF(*pts[(i + 1) % n][:2])
        lp = QtCore.QLineF(v, pv).length()
        ln = QtCore.QLineF(v, nv).length()
        # a neighbour with no rounding of its own lets this corner use the whole edge
        r = min(r, lp if pts[i - 1][2] <= 0 else lp / 2, ln if pts[(i + 1) % n][2] <= 0 else ln / 2)
        a = v + (pv - v) * (r / lp)
        b = v + (nv - v) * (r / ln)
        path.moveTo(a) if i == 0 else path.lineTo(a)
        path.quadTo(v, b)
    path.closeSubpath()
    return path


class CalmText:
    """Text fields that only change when the underlying value moved meaningfully,
    so the bar doesn't flicker every second."""

    def __init__(self):
        self.text = {}
        self.shown = {}   # key -> value the current text was made from
        self.ema = {}

    def smooth(self, key, v):
        if v is None:
            self.ema.pop(key, None)
            return None
        e = self.ema.get(key)
        e = v if e is None else e + (v - e) * SMOOTHING
        self.ema[key] = e
        return e

    def set_num(self, key, v, fmt, step):
        """Update text only if the (smoothed) value moved at least `step` from what's shown.
        step < 1 means relative change (e.g. 0.2 = 20%) - used for network rates."""
        if v is None:
            self.text[key], self.shown[key] = fmt(None), None
            return
        old = self.shown.get(key)
        if old is not None:
            delta = abs(v - old) / max(old, 1.0) if step < 1 else abs(v - old)
            if delta < step:
                return
        self.shown[key], self.text[key] = v, fmt(v)

    def set(self, key, text):
        self.text[key] = text

    def get(self, key):
        return self.text.get(key, "")
