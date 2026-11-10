# LegionNotch

A small system-stats bar for Windows that hangs from the top edge of the screen, shaped like an inverted copy of the Lenovo Legion 5 webcam notch.

- **Collapsed:** CPU, GPU, RAM and network load with small meters, plus the current power mode in the middle.
- **Hover:** expands to 60-second history graphs, the top apps by CPU and memory, GPU and disk details, battery and uptime.
- **Click** a stat to open Task Manager, or the power-mode pill to cycle Quiet → Balanced → Performance.
- **Settings** (gear icon, or right-click): five colour themes, start with Windows, keep expanded, temperatures, GPU power draw.

## Install

Paste this into PowerShell (Windows 10 or 11, no admin rights or Python needed):

```powershell
irm https://raw.githubusercontent.com/apinanaivot/LegionNotch/main/install.ps1 | iex
```

It downloads the latest release to `%LOCALAPPDATA%\Programs\LegionNotch`, adds a Start menu shortcut and launches it. Run it again to update. To start it with Windows, turn on *Start with Windows* under the gear icon.

To uninstall:

```powershell
irm https://raw.githubusercontent.com/apinanaivot/LegionNotch/main/uninstall.ps1 | iex
```

Settings are stored in `%APPDATA%\NotchBar\settings.json`.

## Run from source

Needs Python 3.10+.

```
pip install -r requirements.txt
pythonw notchbar.pyw
```

To build the standalone release zip: `pip install pyinstaller`, then run `.\build.ps1`. The output is `dist\LegionNotch.zip`.

## Hardware notes

- **GPU** stats come from the NVIDIA driver (`nvml.dll`). On AMD or Intel graphics the GPU slot shows `–`.
- **Power mode** is read from Lenovo's Legion service when present, otherwise from the Windows power mode, so it works on most laptops. If neither is available the pill is hidden.
- **CPU temperature** isn't exposed by Windows. Run [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) as administrator with *Options → Remote Web Server* enabled (port 8085) and the bar picks it up automatically.

## Resource use

LegionNotch pauses completely while a fullscreen or maximised app covers it, while the screen is locked and while the display is off. It runs at below-normal priority in Windows efficiency mode, and polls the GPU less often on battery.
