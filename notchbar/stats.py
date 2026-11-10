"""Background thread that samples CPU / RAM / GPU / network / disk once a second."""
import ctypes
import struct
import threading
import time
from collections import deque

import psutil
from PySide6 import QtCore

from .config import GPU_POLL_AC, GPU_POLL_BATTERY, HISTORY
from .gpu import Gpu, query_lhm_cpu_temp

_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                                            ctypes.POINTER(ctypes.c_ulong)]
_buf = [ctypes.create_string_buffer(1 << 20)]


NOT_APPS = {"Memory Compression", "Registry", "Secure System", "vmmem"}


def process_snapshot():
    """Every process's name, total CPU time and private working set from one
    NtQuerySystemInformation call (a few ms, vs. ~0.5 s for opening each process).
    Returns {(pid, create_time): (name, cpu_100ns, private_bytes)} or None."""
    need = ctypes.c_ulong()
    for _ in range(4):
        buf = _buf[0]
        st = _ntdll.NtQuerySystemInformation(5, buf, len(buf), ctypes.byref(need)) & 0xFFFFFFFF
        if st == 0:
            break
        if st != 0xC0000004:            # anything but "buffer too small"
            return None
        _buf[0] = ctypes.create_string_buffer(max(need.value, len(buf)) + (256 << 10))
    else:
        return None
    raw, base, off, out = buf.raw, ctypes.addressof(buf), 0, {}
    while True:   # SYSTEM_PROCESS_INFORMATION, 64-bit layout
        nxt, = struct.unpack_from("<I", raw, off)
        private_ws, = struct.unpack_from("<q", raw, off + 8)
        create, user, kernel = struct.unpack_from("<qqq", raw, off + 32)
        name_len, = struct.unpack_from("<H", raw, off + 56)
        name_ptr, = struct.unpack_from("<Q", raw, off + 64)
        pid, = struct.unpack_from("<Q", raw, off + 80)
        if pid and name_ptr:
            start = name_ptr - base
            name = raw[start:start + name_len].decode("utf-16-le", "replace")
            if name.lower().endswith(".exe"):
                name = name[:-4]
            out[(pid, create)] = (name, user + kernel, private_ws)
        elif pid:   # pid 4 "System" has no image name
            out[(pid, create)] = ("System", user + kernel, private_ws)
        if not nxt:
            return out
        off += nxt


class Stats(QtCore.QObject):
    updated = QtCore.Signal(dict)

    def __init__(self):
        super().__init__()
        self.hist = {k: deque([0.0] * HISTORY, maxlen=HISTORY) for k in ("cpu", "gpu", "ram", "down", "up")}
        self.active = threading.Event()
        self.active.set()
        self.want_procs = threading.Event()   # set by the bar while expanded
        self._procs_t = 0.0
        self._prev = None
        threading.Thread(target=self._run, daemon=True, name="stats").start()

    def _top_procs(self, now):
        """Top CPU / memory apps (grouped by name). Only runs while the bar is expanded;
        returns None while priming the CPU-time baseline, "keep" between samples."""
        if not self.want_procs.is_set():
            self._procs_t, self._prev = 0.0, None
            return None
        if now < self._procs_t:
            return "keep"
        self._procs_t = now + 2.5
        snap = process_snapshot()
        if snap is None:
            return None
        prev, self._prev = self._prev, (now, snap)
        if prev is None:
            return None
        dt = max(now - prev[0], 0.001) * 1e7 * (psutil.cpu_count() or 1)   # 100 ns units, all cores
        cpu, mem = {}, {}
        for key, (name, t, ws) in snap.items():
            if name in NOT_APPS:
                continue
            old = prev[1].get(key)
            if old is not None:
                cpu[name] = cpu.get(name, 0.0) + max(0, t - old[1]) / dt * 100
            mem[name] = mem.get(name, 0) + ws
        top = lambda d: sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:3]
        return {"cpu": top(cpu), "mem": top(mem)}

    def pause(self):
        self.active.clear()

    def resume(self):
        self.active.set()

    def _run(self):
        gpu_dev = Gpu()
        first = True
        while True:
            # (re)start baselines - also after a pause, so rates aren't averaged over the pause
            self.active.wait()
            psutil.cpu_percent(None)
            net0, disk0, t0 = psutil.net_io_counters(), psutil.disk_io_counters(), time.monotonic()
            gpu, cpu_temp, next_gpu, next_lhm = None, None, 0.0, 0.0
            while self.active.is_set():
                time.sleep(1.0)
                if not self.active.is_set():
                    break
                now = time.monotonic()
                dt, t0 = max(now - t0, 0.001), now
                cpu = psutil.cpu_percent(None)
                vm = psutil.virtual_memory()
                net, disk = psutil.net_io_counters(), psutil.disk_io_counters()
                down = max(0, net.bytes_recv - net0.bytes_recv) / dt
                up = max(0, net.bytes_sent - net0.bytes_sent) / dt
                dr = max(0, disk.read_bytes - disk0.read_bytes) / dt if disk and disk0 else 0
                dw = max(0, disk.write_bytes - disk0.write_bytes) / dt if disk and disk0 else 0
                net0, disk0 = net, disk
                bat = psutil.sensors_battery()
                plugged = bat.power_plugged if bat else True

                if now >= next_gpu:
                    gpu = gpu_dev.read()
                    next_gpu = now + (GPU_POLL_AC if plugged else GPU_POLL_BATTERY)
                if now >= next_lhm:   # back off if LibreHardwareMonitor isn't running
                    cpu_temp = query_lhm_cpu_temp()
                    next_lhm = now + (2 if cpu_temp is not None else 30)

                gpu_util = (gpu or {}).get("util") or 0.0
                if first:
                    for k, v in (("cpu", cpu), ("gpu", gpu_util), ("ram", vm.percent)):
                        self.hist[k].extend([v] * HISTORY)
                    first = False
                self.hist["cpu"].append(cpu)
                self.hist["gpu"].append(gpu_util)
                self.hist["ram"].append(vm.percent)
                self.hist["down"].append(down)
                self.hist["up"].append(up)
                procs = self._top_procs(now)
                self.updated.emit({
                    "procs": procs,
                    "batt": (bat.percent, bat.power_plugged, bat.secsleft) if bat else None,
                    "cpu": cpu, "cpu_temp": cpu_temp,
                    "ram": vm.percent, "ram_used": vm.used, "ram_total": vm.total,
                    "gpu": gpu, "down": down, "up": up, "disk_r": dr, "disk_w": dw,
                })
