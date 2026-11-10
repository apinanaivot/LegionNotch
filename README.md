<div align="center">

# LegionNotch

A system monitor in a notch at the top of the screen.

<img src="docs/collapsed.png" width="700" alt="LegionNotch collapsed">

</div>

## Install

Open **PowerShell** (search for it in the Start menu), paste this and press Enter:

```powershell
irm https://raw.githubusercontent.com/apinanaivot/LegionNotch/main/install.ps1 | iex
```

Windows 10 or 11. No admin rights or Python needed. Run it again to update.

## Features

<img src="docs/expanded.png" width="700" alt="LegionNotch expanded">

- CPU, GPU, RAM and network at a glance
- Hover for live graphs and the busiest apps
- Click a graph or app list to open Task Manager
- Click the middle pill to switch power mode
- Pauses under fullscreen apps, on the lock screen and with the display off

<img src="docs/settings.png" width="300" alt="Settings" align="right">

## Settings

Open them with the gear in the expanded view.

- Five colour themes
- Auto-hide: shown only with the mouse at the top centre, click to expand
- Start with Windows
- Keep expanded
- Temperatures and GPU power draw

<br clear="right">

## Notes

- GPU stats need an NVIDIA card.
- CPU temperature needs [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) running with its web server on.

## Uninstall

From settings, or run this in PowerShell:

```powershell
irm https://raw.githubusercontent.com/apinanaivot/LegionNotch/main/uninstall.ps1 | iex
```

<details>
<summary>Run from source</summary>

```
pip install -r requirements.txt
pythonw notchbar.pyw
```

Build the release zip with `pip install pyinstaller` and `.\build.ps1`.

</details>
