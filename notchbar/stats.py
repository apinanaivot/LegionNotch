"""Background thread that samples CPU / RAM / GPU / network / disk once a second."""
import threading
import time
from collections import deque

import psutil
from PySide6 import QtCore

from .config import GPU_POLL_AC, GPU_POLL_BATTERY, HISTORY
from .gpu import Gpu, query_lhm_cpu_temp


class Stats(QtCore.QObject):
    updated = QtCore.Signal(dict)

    def __init__(self):
        super().__init__()
        self.hist = {k: deque([0.0] * HISTORY, maxlen=HISTORY) for k in ("cpu", "gpu", "ram", "down", "up")}
        self.active = threading.Event()
        self.active.set()
        self.want_procs = threading.Event()   # set by the bar while expanded
        self._procs_t = 0.0
        threading.Thread(target=self._run, daemon=True, name="stats").start()

    def _top_procs(self, now):
        """Top CPU / memory apps (grouped by name). Only runs while the bar is expanded;
        returns None while (re)priming the per-process CPU counters."""
        if not self.want_procs.is_set():
            self._procs_t = 0.0
            return None
        if now < self._procs_t:
            return "keep"
        primed = self._procs_t > 0
        self._procs_t = now + 2.5
        ncpu = psutil.cpu_count() or 1
        cpu, mem = {}, {}
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            i = p.info
            name = (i.get("name") or "?")
            if p.pid == 0 or not i.get("memory_info"):
                continue
            name = name[:-4] if name.lower().endswith(".exe") else name
            cpu[name] = cpu.get(name, 0.0) + (i.get("cpu_percent") or 0.0) / ncpu
            mem[name] = mem.get(name, 0) + i["memory_info"].rss
        if not primed:
            return None
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
