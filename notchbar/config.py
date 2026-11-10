"""Tunables, colours and persisted user settings."""
import json
import os

from PySide6 import QtGui

TOP_WIDTH = 518        # width at the screen edge (logical px; 125% scaling -> ~650 physical)
LIP = 11               # flat lip at the screen edge before the 45° slope starts
R_TOP = 11             # outward rounding where the slope leaves the screen edge
R_BEND = 10            # rounding where the slope meets the bar's bottom/side
CORNER = 11            # bottom corner radius when expanded
INSET = LIP + 28       # where content starts (slope depth = COLLAPSED_H)
COLLAPSED_H = 30
EXPANDED_H = 182
HISTORY = 60           # samples of graph history (one per second)
SMOOTHING = 0.35       # 0..1, how fast shown values follow new readings (lower = calmer)
GPU_POLL_AC = 2.0      # seconds between GPU reads when plugged in
GPU_POLL_BATTERY = 10.0
LHM_URL = "http://127.0.0.1:8085/data.json"   # LibreHardwareMonitor web server (optional)
APP_NAME = "NotchBar"

# Palette: graphite surfaces, one neutral ink for data, Legion red only where it means something
# (heavy load, high temperature, the power-mode pill, switches that are on).
BG = QtGui.QColor(10, 10, 12, 250)
EDGE = QtGui.QColor(255, 255, 255, 20)
TXT = QtGui.QColor(232, 234, 238)
DIM = QtGui.QColor(128, 132, 140)
TRACK = QtGui.QColor(255, 255, 255, 20)
CARD = QtGui.QColor(255, 255, 255, 8)
CARD_EDGE = QtGui.QColor(255, 255, 255, 16)

INK = QtGui.QColor(226, 229, 236)        # graphs and meters
INK_DIM = QtGui.QColor(112, 118, 130)    # secondary series (upload)
C_CPU = C_GPU = C_RAM = C_NET = INK
C_NET_UP = INK_DIM
C_WARN = QtGui.QColor(240, 170, 60)
C_HOT = QtGui.QColor(228, 38, 48)        # Legion red: heavy load, always
ACCENT = QtGui.QColor(228, 38, 48)       # switches that are on

# Themes recolour INK / INK_DIM / ACCENT in place, so every module that imported them follows.
# (The power-mode colours are deliberately not themed.)
THEMES = {
    "Graphite": ((226, 229, 236), (112, 118, 130), (228, 38, 48)),
    "Ice":      ((132, 196, 255), (72, 108, 146), (60, 150, 255)),
    "Mint":     ((124, 224, 176), (68, 118, 96), (40, 190, 130)),
    "Amber":    ((255, 190, 92), (140, 108, 62), (245, 158, 40)),
    "Violet":   ((196, 160, 255), (112, 94, 148), (150, 100, 255)),
}


def apply_theme(name):
    ink, dim, accent = THEMES.get(name) or THEMES["Graphite"]
    for col, rgb in ((INK, ink), (INK_DIM, dim), (ACCENT, accent)):
        col.setRgb(*rgb)


# ------------------------------------------------------------------ settings (saved as JSON)
SETTINGS_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME, "settings.json")
DEFAULTS = {"theme": "Graphite", "mode_color": True, "pinned": False, "show_temps": True, "gpu_power": False, "task_manager_click": True}


def load_settings():
    cfg = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg


def save_settings(cfg):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass
