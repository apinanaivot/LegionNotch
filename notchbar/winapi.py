"""Windows integration: z-order/fullscreen detection, power modes, autostart, Task Manager."""
import ctypes
import os
import sys
import winreg
from ctypes import wintypes

import psutil
from PySide6 import QtGui

from .config import APP_NAME

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        h = s.replace("-", "")
        return cls(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                   (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))

    def __str__(self):
        return f"{self.d1:08x}-{self.d2:04x}-{self.d3:04x}-{bytes(self.d4[:2]).hex()}-{bytes(self.d4[2:]).hex()}"


GUID_CONSOLE_DISPLAY_STATE = GUID.parse("6fe69556-704a-47a0-8f24-c28d936fda47")
WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE = 0x0218, 0x8013
WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 0x02B1, 7, 8


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_ubyte * 1)]


DESKTOP_CLASSES = ("Progman", "WorkerW")
HWND_TOP, HWND_BOTTOM = 0, 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
WM_WINDOWPOSCHANGING = 0x0046
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.IsIconic.argtypes = [wintypes.HWND]


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND), ("x", ctypes.c_int),
                ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]


WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                  wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WinEventProc,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def foreground_state(own_hwnd):
    """'desktop'  - the desktop itself is focused (bar should come to the front)
       'covered'  - a fullscreen/maximized app hides the bar completely (pause everything)
       'normal'   - anything else (bar sits behind app windows, still updating)"""
    state = ctypes.c_int()   # fullscreen app / exclusive D3D game / presentation mode
    if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in (2, 3, 4):
        return "covered"
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd == own_hwnd:
        return "normal"
    cls = _class_name(hwnd)
    if cls in DESKTOP_CLASSES:
        return "desktop"
    if cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd") or user32.IsIconic(hwnd):
        return "normal"
    fg, me = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(fg))
    user32.GetWindowRect(own_hwnd, ctypes.byref(me))
    if fg.left <= me.left and fg.top <= me.top and fg.right >= me.right and fg.bottom >= me.bottom:
        return "covered"
    return "normal"


def enable_efficiency_mode():
    """Below-normal priority + EcoQoS: Windows keeps us on efficiency cores at low clocks."""
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass

    class PPTS(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
    try:
        s = PPTS(1, 0x1, 0x1)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED on
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessInformation(wintypes.HANDLE(kernel32.GetCurrentProcess()), 4,
                                       ctypes.byref(s), ctypes.sizeof(s))
    except Exception:
        pass


# Legion power mode (Fn+Q). Lenovo's service mirrors the current mode into this key,
# readable without admin. Fallback: the Windows power-mode overlay Lenovo also switches.
POWER_MODES = {1: ("Quiet", QtGui.QColor(80, 160, 255)),
               2: ("Balanced", QtGui.QColor(225, 228, 235)),
               3: ("Performance", QtGui.QColor(255, 80, 80)),
               224: ("Extreme", QtGui.QColor(255, 80, 200)),
               255: ("Custom", QtGui.QColor(190, 120, 255))}
_OVERLAY_TO_MODE = {"961cc777-2547-4f9d-8174-7d86181b8a7a": 1,
                    "00000000-0000-0000-0000-000000000000": 2,
                    "ded574b5-45a0-4f42-8737-46345c09c238": 3}


def read_power_mode():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Lenovo\SmartEngine\modules\F1020\SmartFanModeEvent") as k:
            v = int(winreg.QueryValueEx(k, "SmartFanMode")[0])
            if v in POWER_MODES:
                return v
    except (OSError, ValueError):
        pass
    try:
        g = GUID()
        ctypes.windll.powrprof.PowerGetEffectiveOverlayScheme(ctypes.byref(g))
        return _OVERLAY_TO_MODE.get(str(g))
    except Exception:
        return None


_MODE_TO_OVERLAY = {v: k for k, v in _OVERLAY_TO_MODE.items()}
MODE_CYCLE = (1, 2, 3)   # Quiet -> Balanced -> Performance, same order as Fn+Q


def set_power_mode(mode):
    """Switch the Windows power mode overlay; Lenovo's service switches the Legion mode to match."""
    try:
        g = GUID.parse(_MODE_TO_OVERLAY[mode])
        return ctypes.windll.powrprof.PowerSetActiveOverlayScheme(ctypes.byref(g)) == 0
    except Exception:
        return False


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            if getattr(sys, "frozen", False):      # packaged LegionNotch.exe
                cmd = f'"{sys.executable}"'
            else:
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                cmd = f'"{pyw}" "{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def is_installed():
    """True when running as the packaged exe from the installer's folder."""
    if not getattr(sys, "frozen", False):
        return False
    want = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "LegionNotch")
    return os.path.normcase(os.path.dirname(sys.executable)) == os.path.normcase(want)


def uninstall_self():
    """Remove the startup entry, settings and shortcut now, and the install folder once this process exits."""
    import shutil
    import subprocess
    try:
        set_startup(False)
    except OSError:
        pass
    shutil.rmtree(os.path.join(os.environ.get("APPDATA", ""), APP_NAME), ignore_errors=True)
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\LegionNotch.lnk")
    try:
        os.remove(lnk)
    except OSError:
        pass
    folder = os.path.dirname(sys.executable).replace("'", "''")
    script = (f"Wait-Process -Id {os.getpid()} -Timeout 15 -ErrorAction SilentlyContinue; "
              f"for ($i = 0; (Test-Path '{folder}') -and $i -lt 20; $i++) "
              f"{{ Remove-Item '{folder}' -Recurse -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 500 }}")
    args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    io = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              cwd=os.environ.get("TEMP"), close_fds=True)
    try:   # outlive this process even if it was started inside a job object
        subprocess.Popen(args, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **io)
    except OSError:
        subprocess.Popen(args, creationflags=base, **io)


def open_task_manager():
    try:
        shell32.ShellExecuteW(None, "open", "taskmgr.exe", None, None, 1)
    except Exception:
        pass
