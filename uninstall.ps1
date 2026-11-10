# LegionNotch uninstaller. Run in PowerShell:
#   irm https://raw.githubusercontent.com/apinanaivot/LegionNotch/main/uninstall.ps1 | iex

& {
    Get-Process LegionNotch -ErrorAction SilentlyContinue | Stop-Process -Force
    Wait-Process LegionNotch -Timeout 10 -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    Remove-Item (Join-Path $env:LOCALAPPDATA "Programs\LegionNotch") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "LegionNotch.lnk") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:APPDATA "NotchBar") -Recurse -Force -ErrorAction SilentlyContinue

    # the startup entry is only removed if it points at the installed exe
    $run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $val = (Get-ItemProperty $run -Name NotchBar -ErrorAction SilentlyContinue).NotchBar
    if ($val -like "*LegionNotch.exe*") { Remove-ItemProperty $run -Name NotchBar }

    Write-Host "LegionNotch has been removed."
}
