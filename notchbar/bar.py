"""The notch bar widget: layout, painting, interaction."""
import ctypes
import time
from ctypes import wintypes

import psutil
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt

from .config import *
from .helpers import *
from .settings_popup import SettingsPopup
from .winapi import *


class NotchBar(QtWidgets.QWidget):
    def __init__(self, stats):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(TOP_WIDTH, COLLAPSED_H + 2)   # grows only while expanded
        self.stats = stats
        self.hist = stats.hist
        stats.updated.connect(self._on_stats)

        self.cfg = load_settings()
        apply_theme(self.cfg["theme"])
        self.h = float(COLLAPSED_H)
        self.pinned = bool(self.cfg["pinned"])
        self.hits = []                # (rect, action) rebuilt on every paint
        self.popup = None
        self.popup_open = False
        self.snap = None
        self.blocked = set()          # reasons we're hidden: fullscreen / locked / display_off
        self.clock = QtCore.QElapsedTimer()
        self.clock.start()
        self.texts = CalmText()
        self.meters = {k: [0.0, 0.0] for k in ("cpu", "gpu", "ram", "net")}   # [shown, target]
        self.colors = {}
        self.boot = psutil.boot_time()
        self._shape_cache = (None, None)

        self.anim = QtCore.QVariantAnimation(self)
        self.anim.setDuration(240)
        self.anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set_h)

        # one frame timer, only running while a fade/meter glide is in progress
        self.ticker = QtCore.QTimer(self, interval=33)
        self.ticker.timeout.connect(self._tick)
        self.last_tick = 0

        self.collapse_timer = QtCore.QTimer(self, singleShot=True, interval=350)
        self.collapse_timer.timeout.connect(lambda: self._animate_to(COLLAPSED_H))

        # z-order / coverage: reacts instantly to focus changes via a WinEvent hook,
        # plus a slow poll for things the hook doesn't report (maximize, resize)
        self.desktop_front = False
        self.fs_timer = QtCore.QTimer(self, interval=2000)
        self.fs_timer.timeout.connect(self._check_front)
        self.fs_timer.start()
        self._hook_proc = WinEventProc(lambda *a: QtCore.QTimer.singleShot(30, self._check_front))
        self._hooks = [user32.SetWinEventHook(lo, hi, None, self._hook_proc, 0, 0, 0)  # OUTOFCONTEXT
                       for lo, hi in ((0x0003, 0x0003),    # foreground changed
                                      (0x0016, 0x0017),    # minimize start/end
                                      (0x000B, 0x000B))]   # move/size end

        self.mode = read_power_mode()
        self.mode_timer = QtCore.QTimer(self, interval=700)
        self.mode_timer.timeout.connect(self._poll_mode)
        self.mode_timer.start()
        self._update_tip()

        QtGui.QGuiApplication.primaryScreen().geometryChanged.connect(self._place)
        self._place()

        self.batt = None
        self.f_label = font(10, QtGui.QFont.Weight.DemiBold)
        self.f_label.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.2)
        self.f_val = font(11, QtGui.QFont.Weight.DemiBold)
        self.f_small = font(11)
        self.f_card_val = font(13, QtGui.QFont.Weight.DemiBold)
        self.f_detail = font(10)
        fm = QtGui.QFontMetricsF(self.f_label)
        self.label_w = {k: fm.horizontalAdvance(k) + 6 for k in ("CPU", "GPU", "RAM", "NET")}
        self._notifications_registered = False
        self.pill_rect = QRectF()
        self.gear_rect = QRectF()
        self.setMouseTracking(True)
        if self.pinned:
            self._set_h(EXPANDED_H)

        # auto-hide: hidden (and not sampling) until the mouse touches the top edge above the bar
        self.reveal_timer = QtCore.QTimer(self, interval=120)
        self.reveal_timer.timeout.connect(self._check_reveal)
        self.slide = 1.0                     # 0 = tucked above the screen edge, 1 = fully shown
        self.slide_anim = QtCore.QVariantAnimation(self)
        self.slide_anim.setDuration(220)
        self.slide_anim.valueChanged.connect(self._set_slide)
        self.slide_anim.finished.connect(self._slide_done)
        self.hide_timer = QtCore.QTimer(self, singleShot=True, interval=700)
        self.hide_timer.timeout.connect(self._auto_hide)
        if self.cfg["auto_hide"] and not self.pinned:
            QtCore.QTimer.singleShot(0, self._auto_hide)

    # -- Windows notifications: lock/unlock and display on/off
    def showEvent(self, e):
        if not self._notifications_registered:
            hwnd = int(self.winId())
            try:
                ctypes.windll.wtsapi32.WTSRegisterSessionNotification(wintypes.HWND(hwnd), 0)
                user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0)
            except Exception:
                pass
            self._notifications_registered = True
        super().showEvent(e)

    def nativeEvent(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_WINDOWPOSCHANGING and not self._front():
                # keep the bar at the bottom of the z-order (on the desktop) whatever happens
                wp = WINDOWPOS.from_address(msg.lParam)
                if not wp.flags & SWP_NOZORDER:
                    wp.hwndInsertAfter = HWND_BOTTOM
            elif msg.message == WM_WTSSESSION_CHANGE:
                if msg.wParam == WTS_SESSION_LOCK:
                    self._set_blocked("locked", True)
                elif msg.wParam == WTS_SESSION_UNLOCK:
                    self._set_blocked("locked", False)
            elif msg.message == WM_POWERBROADCAST and msg.wParam == PBT_POWERSETTINGCHANGE and msg.lParam:
                pbs = POWERBROADCAST_SETTING.from_address(msg.lParam)
                if str(pbs.PowerSetting) == str(GUID_CONSOLE_DISPLAY_STATE):
                    self._set_blocked("display_off", pbs.Data[0] == 0)
        except Exception:
            pass
        return False, 0

    # -- placement / visibility
    def _place(self):
        g = QtGui.QGuiApplication.primaryScreen().geometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y())

    def _check_front(self):
        hwnd = int(self.winId())
        try:
            state = foreground_state(hwnd)
        except Exception:
            state = "normal"
        self._set_blocked("covered", state == "covered")
        front = state == "desktop"
        if front != self.desktop_front:
            self.desktop_front = front
            if self.isVisible():
                self._apply_z()

    def _front(self):
        """On top of other windows while the desktop is focused (e.g. after Win+D),
        or always in auto-hide mode, where it's only visible when asked for."""
        return self.desktop_front or self.cfg["auto_hide"]

    def _apply_z(self):
        user32.SetWindowPos(int(self.winId()), HWND_TOP if self._front() else HWND_BOTTOM,
                            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _set_blocked(self, reason, on):
        before = bool(self.blocked)
        (self.blocked.add if on else self.blocked.discard)(reason)
        if bool(self.blocked) == before:
            return
        if self.blocked:   # go fully idle
            self.stats.pause()
            self.mode_timer.stop()
            self.ticker.stop()
            self.hide()
        else:
            self.stats.resume()
            self.mode_timer.start()
            self._poll_mode()
            self.show()
            self._apply_z()
            if self.cfg["auto_hide"] and not self._mouse_over():
                self.hide_timer.start()

    def _mouse_over(self):
        return self.geometry().contains(QtGui.QCursor.pos())

    def _set_slide(self, v):
        self.slide = float(v)
        self.update()

    def _slide_to(self, target):
        self.slide_anim.stop()
        self.slide_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic if target > self.slide
                                       else QtCore.QEasingCurve.InCubic)
        self.slide_anim.setStartValue(self.slide)
        self.slide_anim.setEndValue(float(target))
        self.slide_anim.start()

    def _slide_done(self):
        if self.slide > 0.01:
            return
        if self._should_hide():              # fully tucked away: stop everything until revealed again
            self.anim.stop()
            self._set_h(COLLAPSED_H)
            self._set_blocked("autohide", True)
            self.reveal_timer.start()
        else:                                # hovered again during the slide-out
            self._slide_to(1.0)

    def _check_reveal(self):
        pos = QtGui.QCursor.pos()
        g = QtGui.QGuiApplication.primaryScreen().geometry()
        if pos.y() <= g.top() + 1 and self.x() + LIP <= pos.x() <= self.x() + self.width() - LIP:
            self.reveal_timer.stop()
            self.slide = 0.0
            self._set_blocked("autohide", False)
            self._slide_to(1.0)

    def _should_hide(self):
        return (self.cfg["auto_hide"] and not self.pinned and not self.popup_open
                and not self._mouse_over())

    def _auto_hide(self):
        if self._should_hide():
            self._slide_to(0.0)

    def _update_tip(self):
        name = POWER_MODES.get(self.mode, ("?",))[0]
        self.setToolTip("" if self.mode is None else f"Power mode: {name} (click to change)")

    def _poll_mode(self):
        m = read_power_mode()
        if m != self.mode:
            self.mode = m
            self._update_tip()
            self.update()

    # -- stats -> fade targets
    def _on_stats(self, s):
        if self.blocked:
            return
        self.snap = s
        T = self.texts
        g = s["gpu"] or {}
        gu = g.get("util")
        if gu is None and g:
            gu = 0.0   # a sleeping dGPU sometimes doesn't report load: that means idle
        pct = lambda v: "–" if v is None else f"{v:.0f}%"
        deg = lambda v: "" if v is None else f"{v:.0f}°"
        rate = lambda v: fmt_rate(v or 0)

        cpu, gpu, ram = T.smooth("cpu", s["cpu"]), T.smooth("gpu", gu), T.smooth("ram", s["ram"])
        ct, gt = T.smooth("cpu_t", s["cpu_temp"]), T.smooth("gpu_t", g.get("temp"))
        down, up = T.smooth("down", s["down"]), T.smooth("up", s["up"])
        T.set_num("cpu", cpu, pct, 3)
        T.set_num("gpu", gpu, pct, 3)
        T.set_num("ram", ram, pct, 1)
        T.set_num("cpu_t", ct, deg, 2)
        T.set_num("gpu_t", gt, deg, 2)
        T.set_num("ram_g", s["ram_used"] / 2**30, lambda v: f"{v:.1f}G", 0.2)
        T.set_num("down", down, lambda v: f"↓ {rate(v)}", 0.25)
        T.set_num("up", up, rate, 0.25)
        T.set("c_mem", f"{s['ram_used'] / 2**30:.1f}/{s['ram_total'] / 2**30:.0f}G")
        T.set("c_net", f"↓ {rate(down)}" + chr(10) + f"↑ {rate(up)}")
        parts = []
        if g:
            bits = [g["name"]]
            if g.get("mem_used") is not None and g.get("mem_total"):
                bits.append(f"{g['mem_used'] / 1024:.1f}/{g['mem_total'] / 1024:.0f} GB")
            if self.cfg["gpu_power"] and g.get("power") is not None:
                bits.append(f"{g['power']:.0f} W")
            parts.append(" · ".join(bits))
        parts.append(f"Disk R {rate(s['disk_r'])}  W {rate(s['disk_w'])}")
        T.set("detail", "     ".join(parts))
        pr = s.get("procs")
        if isinstance(pr, dict):
            short = lambda n: n if len(n) <= 16 else n[:15] + "…"
            T.set("p_cpu", "  ·  ".join(f"{short(n)} {v:.0f}%" for n, v in pr["cpu"]))
            T.set("p_mem", "  ·  ".join(f"{short(n)} {v / 2**30:.1f}G" if v >= 2**30 else f"{short(n)} {v / 2**20:.0f}M"
                                         for n, v in pr["mem"]))
        elif pr is None and self.h > COLLAPSED_H and not T.get("p_cpu"):
            T.set("p_cpu", "–")
            T.set("p_mem", "–")
        b = s.get("batt")
        if b:
            pc, plug, left = b
            txt = f"{pc:.0f}%"
            if not plug and left and left > 0:
                txt += f"  {left // 3600}h {left % 3600 // 60}m"
            T.set("batt", txt)
        else:
            T.set("batt", "")
        self.batt = b
        self.colors = {"cpu_t": temp_color(ct), "gpu_t": temp_color(gt)}

        peak = max(64 * 1024, max(self.hist["down"]))
        for k, v in (("cpu", cpu), ("gpu", gpu), ("ram", ram)):
            self.meters[k][1] = max(0.0, min(1.0, (v or 0) / 100))
        self.meters["net"][1] = max(0.0, min(1.0, (down or 0) / peak))
        # tiny moves just snap (no animation frames); only visible changes glide
        changed = False
        for m in self.meters.values():
            if abs(m[1] - m[0]) < 0.02:
                if m[0] != m[1]:
                    m[0] = m[1]
                    changed = True
            else:
                changed = True
        if changed or self.h > COLLAPSED_H:
            self._kick()

    def _kick(self):
        if not self.ticker.isActive() and any(abs(m[1] - m[0]) > 0.004 for m in self.meters.values()):
            self.last_tick = self.clock.elapsed()
            self.ticker.start()
        self.update()

    def _tick(self):
        now = self.clock.elapsed()
        dt = max(1, now - self.last_tick) / 1000
        self.last_tick = now
        k = 1 - pow(0.002, dt)           # frame-rate independent glide, ~0.6 s to settle
        moving = False
        for m in self.meters.values():
            d = m[1] - m[0]
            if abs(d) > 0.004:
                m[0] += d * k
                moving = True
            else:
                m[0] = m[1]
        if not moving:
            self.ticker.stop()
        self.update()

    # -- expand / collapse
    def _set_h(self, v):
        self.h = float(v)
        if self.h > COLLAPSED_H + 1:        # per-app sampling only while expanded
            self.stats.want_procs.set()
        else:
            self.stats.want_procs.clear()
            self.texts.set("p_cpu", "")
            self.texts.set("p_mem", "")
        want = int(self.h + 0.999) + 2
        if want != self.height():
            self.setFixedSize(TOP_WIDTH, want)
        self.update()

    def _animate_to(self, target):
        self.anim.stop()
        self.anim.setStartValue(self.h)
        self.anim.setEndValue(float(target))
        self.anim.start()

    def enterEvent(self, e):
        self.collapse_timer.stop()
        self.hide_timer.stop()
        if self.slide < 1.0 and self.slide_anim.endValue() == 0.0:
            self._slide_to(1.0)              # hovered during the slide-out: reverse it
        if not self.cfg["auto_hide"]:
            self._animate_to(EXPANDED_H)

    def leaveEvent(self, e):
        if not self.pinned and not self.popup_open:
            if self.cfg["auto_hide"]:
                self.hide_timer.start()      # slide out at the current size, then reset to the small bar
            else:
                self.collapse_timer.start()

    def after_popup(self):
        if not self.pinned and not self._mouse_over():
            if self.cfg["auto_hide"]:
                self.hide_timer.start()
            else:
                self.collapse_timer.start()

    # -- clickable regions (rebuilt every paint)
    def _hit(self, pos):
        for rect, action in self.hits:
            if rect.contains(pos):
                if action == "taskmgr" and not self.cfg["task_manager_click"]:
                    continue
                return action
        if self.cfg["auto_hide"] and self.h < COLLAPSED_H + 1 and pos.y() <= COLLAPSED_H:
            return "expand"
        return None

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.PointingHandCursor if self._hit(e.position()) else Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        action = self._hit(e.position())
        if action == "mode":
            cur = self.mode if self.mode in MODE_CYCLE else MODE_CYCLE[-1]
            nxt = MODE_CYCLE[(MODE_CYCLE.index(cur) + 1) % len(MODE_CYCLE)]
            if set_power_mode(nxt):
                self.mode = nxt          # optimistic; _poll_mode confirms within a second
                self._update_tip()
                self.update()
        elif action == "expand":
            self._animate_to(EXPANDED_H)
        elif action == "taskmgr":
            open_task_manager()
        elif action == "gear":
            self.open_settings()

    # -- settings
    def open_settings(self):
        if self.popup is None:
            self.popup = SettingsPopup(self)
        if self.popup.isVisible():
            self.popup.hide()
            return
        self.collapse_timer.stop()
        self.popup.popup_at(self.mapToGlobal(QtCore.QPoint(int(self.gear_rect.right()), self.height())))

    def apply_setting(self, key, on):
        if key == "startup":
            try:
                set_startup(on)
            except OSError:
                pass
            return
        if key == "pinned":
            self.pinned = on
            self._animate_to(EXPANDED_H)   # stays open while the popup is; collapses after it closes
        self.cfg[key] = on
        save_settings(self.cfg)
        if key == "auto_hide":
            if on:
                self._apply_z()
                self.hide_timer.start()     # once the settings close and the mouse is elsewhere
            else:
                self.reveal_timer.stop()
                self.slide_anim.stop()
                self._set_slide(1.0)
                self._set_blocked("autohide", False)
                self._apply_z()
        if key == "theme":
            apply_theme(on)
            if self.popup:
                for w in self.popup.findChildren(QtWidgets.QWidget):
                    w.update()
        if key == "gpu_power" and self.snap:
            self._on_stats(self.snap)
        self.update()

    def contextMenuEvent(self, e):
        m = QtWidgets.QMenu(self)
        m.setStyleSheet(
            "QMenu{background:#16171b;color:#e8eaee;border:1px solid #2a2c31;padding:4px;border-radius:6px}"
            "QMenu::item{padding:5px 18px 5px 10px;border-radius:4px}"
            "QMenu::item:selected{background:#2a2d34}")
        settings = m.addAction("Settings…")
        m.addSeparator()
        quit_ = m.addAction("Quit")
        act = m.exec(e.globalPos())
        if act is settings:
            self._animate_to(EXPANDED_H)
            QtCore.QTimer.singleShot(260, self.open_settings)
        elif act is quit_:
            QtWidgets.QApplication.quit()

    # -- painting
    def _shape(self, h):
        """Inverted Legion notch: 45° slopes down from the screen edge, flat bottom.
        When expanded, the sides continue straight down below the slope."""
        if self._shape_cache[0] == h:
            return self._shape_cache[1]
        W, d = float(self.width()), float(COLLAPSED_H)
        hh = max(h, d)
        a = LIP + d  # x where the slope ends
        pts = [(0, 0, 0), (LIP, 0, R_TOP), (a, d, R_BEND)]
        if hh > d + 0.5:
            pts.append((a, hh, CORNER))
            pts.append((W - a, hh, CORNER))
        pts += [(W - a, d, R_BEND), (W - LIP, 0, R_TOP), (W, 0, 0)]
        path = rounded_polygon(pts)
        self._shape_cache = (h, path)
        return path

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.slide < 1.0:
            p.translate(0, -(1.0 - self.slide) * self.height())
        shape = self._shape(self.h)
        p.fillPath(shape, BG)
        p.setPen(QtGui.QPen(EDGE, 1))
        p.drawPath(shape.translated(0, -0.5))
        p.setClipPath(shape)
        self.hits = []
        if self.snap is None:
            return
        now = self.clock.elapsed()
        self._paint_row(p, now)
        t = (self.h - COLLAPSED_H) / (EXPANDED_H - COLLAPSED_H)
        if t > 0.02:
            p.setOpacity(min(1.0, t * 1.4))
            self._paint_expanded(p, now)

    def _text(self, p, key, rect, align, fnt, color, now=None):
        text = self.texts.get(key)
        if text:
            p.setFont(fnt)
            p.setPen(color)
            p.drawText(rect, align, text)

    def _paint_row(self, p, now):
        W = self.width()
        x0, gap, mid = INSET, 10, 46
        cx = W / 2
        sw = (cx - mid / 2 - x0 - 2 * gap) / 2
        rx = cx + mid / 2 + gap
        slots = [QRectF(x0, 0, sw, COLLAPSED_H), QRectF(x0 + sw + gap, 0, sw, COLLAPSED_H),
                 QRectF(rx, 0, sw, COLLAPSED_H), QRectF(rx + sw + gap, 0, sw, COLLAPSED_H)]
        self._paint_mode(p, QRectF(cx - mid / 2, 0, mid, COLLAPSED_H))
        temps = self.cfg["show_temps"]
        self._slot(p, slots[0], "CPU", "cpu", "cpu_t" if temps else "", self.colors.get("cpu_t", DIM), "cpu", C_CPU, now)
        self._slot(p, slots[1], "GPU", "gpu", "gpu_t" if temps else "", self.colors.get("gpu_t", DIM), "gpu", C_GPU, now)
        self._slot(p, slots[2], "RAM", "ram", "ram_g", DIM, "ram", C_RAM, now)
        self._slot(p, slots[3], "NET", "down", "", DIM, "net", C_NET, now)

    def _paint_mode(self, p, r):
        """Power mode as a small pill: three bars that fill up Quiet -> Balanced -> Performance."""
        if self.mode is None:      # no power-mode support on this machine: no pill, no button
            self.pill_rect = QRectF()
            return
        _, col = POWER_MODES.get(self.mode, ("?", DIM))
        if not self.cfg["mode_color"]:
            col = INK
        level = {1: 1, 2: 2, 3: 3, 224: 3, 255: 3}.get(self.mode, 0)
        pill = QRectF(r.center().x() - 20, 6, 40, 15)
        self.pill_rect = pill
        self.hits.insert(0, (pill.adjusted(-4, -4, 4, 4), "mode"))
        bg = QtGui.QColor(col)
        bg.setAlpha(38)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 7.5, 7.5)
        bw, bgap = 4.0, 3.0
        bx = pill.center().x() - (3 * bw + 2 * bgap) / 2
        for i in range(3):
            hgt = 4 + i * 2.5
            c = QtGui.QColor(col)
            if i >= level:
                c.setAlpha(55)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(bx + i * (bw + bgap), pill.bottom() - 3.5 - hgt, bw, hgt), 1.2, 1.2)
        if self.mode == 255:  # custom: small dot to tell it apart from performance
            p.setBrush(col)
            p.drawEllipse(QPointF(pill.right() - 6, pill.top() + 4), 1.6, 1.6)

    def _slot(self, p, r, label, val_key, extra_key, extra_col, meter, col, now):
        text_r = QRectF(r.x(), 0, r.width(), COLLAPSED_H - 4)
        lw = 0
        if label:
            p.setFont(self.f_label)
            p.setPen(DIM)
            p.drawText(text_r, Qt.AlignVCenter | Qt.AlignLeft, label)
            lw = self.label_w[label]
        self._text(p, val_key, text_r.adjusted(lw, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.f_val, TXT, now)
        self._text(p, extra_key, text_r, Qt.AlignVCenter | Qt.AlignRight, self.f_small, extra_col, now)
        bar = QRectF(r.x(), COLLAPSED_H - 6.5, r.width(), 2.5)
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(bar, 1.25, 1.25)
        frac = self.meters[meter][0]
        if frac > 0.004:
            if meter != "net":     # only heavy load gets colour
                col = C_HOT if frac >= 0.9 else C_WARN if frac >= 0.75 else col
            p.setBrush(col)
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(2.5, bar.width() * frac), bar.height()), 1.25, 1.25)

    def _paint_expanded(self, p, now):
        W = self.width()
        x0, x1 = LIP + COLLAPSED_H + 8, W - LIP - COLLAPSED_H - 8
        top, ch, gap = COLLAPSED_H + 8, 86, 8
        cw = (x1 - x0 - 3 * gap) / 4
        net_max = max(64 * 1024, max(self.hist["down"]), max(self.hist["up"])) * 1.15
        cards = [
            ("CPU", "cpu", self.f_card_val, [(self.hist["cpu"], C_CPU)], 100),
            ("GPU", "gpu", self.f_card_val, [(self.hist["gpu"], C_GPU)], 100),
            ("Memory", "c_mem", self.f_card_val, [(self.hist["ram"], C_RAM)], 100),
            ("Network", "c_net", self.f_detail, [(self.hist["down"], C_NET), (self.hist["up"], C_NET_UP)], net_max),
        ]
        for i, (label, key, fnt, series, vmax) in enumerate(cards):
            r = QRectF(x0 + i * (cw + gap), top, cw, ch)
            if self.h > EXPANDED_H - 6:
                self.hits.append((r, "taskmgr"))
            p.setPen(QtGui.QPen(CARD_EDGE, 1))
            p.setBrush(CARD)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            inner = r.adjusted(9, 7, -9, -6)
            p.setFont(self.f_label)
            p.setPen(DIM)
            p.drawText(inner, Qt.AlignLeft | Qt.AlignTop, label)
            self._text(p, key, inner.adjusted(0, 12, 0, 0), Qt.AlignLeft | Qt.AlignTop, fnt, TXT, now)
            graph = QRectF(r.x() + 1, r.y() + 38, r.width() - 2, r.height() - 39)
            for j, (data, col) in enumerate(series):
                self._spark(p, graph, data, vmax, col, fill=(j == 0))

        up = int(time.time() - self.boot)
        uptime = f"up {up // 86400}d {up % 86400 // 3600}h" if up >= 86400 else f"up {up // 3600}h {up % 3600 // 60}m"
        # top apps by CPU / memory (only sampled while expanded); click opens Task Manager
        fm = QtGui.QFontMetricsF(self.f_detail)
        for n, (lab, key) in enumerate((("Top CPU", "p_cpu"), ("Top memory", "p_mem"))):
            row = QRectF(x0 + 2, top + ch + 3 + n * 15, x1 - x0 - 4, 15)
            p.setFont(self.f_label)
            p.setPen(DIM)
            p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft, lab)
            self._text(p, key, row.adjusted(66, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.f_detail, TXT, now)
            if self.h > EXPANDED_H - 6:
                self.hits.append((row, "taskmgr"))
        line = QRectF(x0 + 2, top + ch + 3 + 30, x1 - x0 - 4, EXPANDED_H - (top + ch + 33) - 3)
        self._text(p, "detail", line, Qt.AlignVCenter | Qt.AlignLeft, self.f_detail, DIM, now)
        # right side, from the gear inwards: gear | uptime | battery icon + text
        self.gear_rect = QRectF(line.right() - 16, line.center().y() - 8, 16, 16)
        if self.h > EXPANDED_H - 6:
            self.hits.append((self.gear_rect.adjusted(-4, -4, 4, 4), "gear"))
        gf = QtGui.QFont("Segoe Fluent Icons")
        gf.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
        gf.setPixelSize(14)
        p.setFont(gf)
        p.setPen(TXT if self.popup_open else DIM)
        p.drawText(self.gear_rect, Qt.AlignCenter, "")
        p.setFont(self.f_detail)
        p.setPen(DIM)
        x = self.gear_rect.left() - 12
        w_up = fm.horizontalAdvance(uptime)
        p.drawText(QRectF(x - w_up, line.y(), w_up + 1, line.height()), Qt.AlignVCenter | Qt.AlignRight, uptime)
        x -= w_up
        batt, b = self.texts.get("batt"), self.batt
        if b:
            w_b = fm.horizontalAdvance(batt) + 22
            if x - w_b - 14 > line.x() + fm.horizontalAdvance(self.texts.get("detail")) + 12:
                x -= 14
                p.drawText(QRectF(x - w_b + 22, line.y(), w_b - 22, line.height()), Qt.AlignVCenter | Qt.AlignRight, batt)
                self._paint_battery(p, QRectF(x - w_b, line.center().y() - 4.5, 16, 9), b[0], b[1])

    @staticmethod
    def _paint_battery(p, r, pct, plugged):
        """Small outline battery with a fill level; a bolt cut-out while charging."""
        col = C_HOT if pct <= 15 and not plugged else TXT
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(DIM, 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
        p.setPen(Qt.NoPen)
        p.setBrush(DIM)
        p.drawRect(QRectF(r.right() + 0.5, r.center().y() - 2, 1.5, 4))
        inner = r.adjusted(2, 2, -2, -2)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(inner.x(), inner.y(), max(1.0, inner.width() * pct / 100), inner.height()), 0.8, 0.8)
        if plugged:
            c = r.center()
            bolt = QtGui.QPolygonF([QPointF(c.x() + 1.4, r.y() - 0.8), QPointF(c.x() - 2.4, c.y() + 0.6),
                                    QPointF(c.x() - 0.1, c.y() + 0.6), QPointF(c.x() - 1.4, r.bottom() + 0.8),
                                    QPointF(c.x() + 2.4, c.y() - 0.8), QPointF(c.x() + 0.1, c.y() - 0.8)])
            p.setPen(QtGui.QPen(BG, 1.2))
            p.setBrush(INK)
            p.drawPolygon(bolt)

    @staticmethod
    def _spark(p, r, data, vmax, col, fill=True):
        n = len(data)
        if n < 2 or vmax <= 0:
            return
        step = r.width() / (n - 1)
        line = QtGui.QPainterPath()
        for i, v in enumerate(data):
            pt = QPointF(r.x() + i * step, r.bottom() - min(v / vmax, 1.0) * (r.height() - 2))
            line.moveTo(pt) if i == 0 else line.lineTo(pt)
        if fill:
            area = QtGui.QPainterPath(line)
            area.lineTo(r.right(), r.bottom())
            area.lineTo(r.left(), r.bottom())
            area.closeSubpath()
            grad = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
            c1, c2 = QtGui.QColor(col), QtGui.QColor(col)
            c1.setAlpha(90)
            c2.setAlpha(0)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.fillPath(area, grad)
        pen = QtGui.QPen(col, 1.4)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)
