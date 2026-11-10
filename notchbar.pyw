"""
Notch Bar - a small system-stats bar that hangs from the top edge of the screen,
shaped like an inverted copy of the Legion 5 webcam notch.

  * Collapsed: CPU / GPU  |  power mode (Fn+Q)  |  RAM / network, each with a load meter.
  * Hover it: expands to show 60-second history graphs + GPU/disk/uptime details.
  * Click any stat to open Task Manager; the gear in the expanded view opens settings.
  * Right-click: settings, quit.

CPU temperature: if LibreHardwareMonitor's remote web server is running (port 8085),
the bar picks the CPU package temperature up from it automatically.

Layout: notchbar/{config,gpu,stats,helpers,winapi,settings_popup,bar}.py

Run:  pythonw notchbar.pyw     (needs: pip install PySide6 psutil)
"""
import os
import sys
import tempfile

from PySide6 import QtCore, QtWidgets

from notchbar.bar import NotchBar
from notchbar.stats import Stats
from notchbar.winapi import enable_efficiency_mode


def main():
    enable_efficiency_mode()
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QtCore.QLockFile(os.path.join(tempfile.gettempdir(), "notchbar.lock"))
    if not lock.tryLock(100):
        return  # already running
    stats = Stats()
    bar = NotchBar(stats)
    bar.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
