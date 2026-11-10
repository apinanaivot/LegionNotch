"""GPU stats straight from the NVIDIA driver (nvml.dll), nvidia-smi fallback, plus the optional LHM CPU temp."""
import ctypes
import json
import subprocess
import urllib.request

from .config import LHM_URL


class _NvUtil(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvMem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _short_gpu_name(name):
    return name.replace("NVIDIA ", "").replace("GeForce ", "").replace(" Laptop GPU", "")


class Gpu:
    def __init__(self):
        self.nv = self.h = None
        self.name = "GPU"
        try:
            self.nv = ctypes.WinDLL("nvml.dll")
            if self.nv.nvmlInit_v2() != 0:
                raise OSError
            h = ctypes.c_void_p()
            if self.nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) != 0:
                raise OSError
            self.h = h
            buf = ctypes.create_string_buffer(96)
            if self.nv.nvmlDeviceGetName(h, buf, 96) == 0:
                self.name = _short_gpu_name(buf.value.decode(errors="ignore"))
        except Exception:
            self.nv = self.h = None

    def read(self):
        if self.h is None:
            return self._read_smi()
        nv, h = self.nv, self.h
        temp, power, util, mem = ctypes.c_uint(), ctypes.c_uint(), _NvUtil(), _NvMem()
        out = {"name": self.name, "temp": None, "util": None, "mem_used": None, "mem_total": None, "power": None}
        if nv.nvmlDeviceGetTemperature(h, 0, ctypes.byref(temp)) == 0:
            out["temp"] = float(temp.value)
        if nv.nvmlDeviceGetUtilizationRates(h, ctypes.byref(util)) == 0:
            out["util"] = float(util.gpu)
        if nv.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)) == 0:
            out["mem_used"], out["mem_total"] = mem.used / 2**20, mem.total / 2**20
        if nv.nvmlDeviceGetPowerUsage(h, ctypes.byref(power)) == 0:
            out["power"] = power.value / 1000
        return out

    @staticmethod
    def _read_smi():
        try:
            line = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout.strip().splitlines()[0]
            parts = [x.strip() for x in line.split(",")]

            def num(s):
                try:
                    return float(s)
                except ValueError:
                    return None
            return {"name": _short_gpu_name(parts[0]), "temp": num(parts[1]), "util": num(parts[2]),
                    "mem_used": num(parts[3]), "mem_total": num(parts[4]), "power": num(parts[5])}
        except Exception:
            return None


def query_lhm_cpu_temp():
    """CPU package temp from LibreHardwareMonitor's web server, if it's running."""
    try:
        with urllib.request.urlopen(LHM_URL, timeout=0.5) as r:
            data = json.load(r)
    except Exception:
        return None
    keys = ("CPU Package", "Core (Tctl/Tdie)", "Core Max", "Core Average")
    found, stack = {}, [data]
    while stack:
        node = stack.pop()
        text, val = node.get("Text", ""), node.get("Value", "")
        if text in keys and "°C" in val:
            try:
                found.setdefault(text, float(val.split()[0].replace(",", ".")))
            except ValueError:
                pass
        stack.extend(node.get("Children", []))
    return next((found[k] for k in keys if k in found), None)
