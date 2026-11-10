# LegionNotch installer. Run in PowerShell:
#   irm https://raw.githubusercontent.com/apinanaivot/LegionNotch/main/install.ps1 | iex
# Installs the latest release to %LOCALAPPDATA%\Programs\LegionNotch, adds a Start menu shortcut and launches it.
# No admin rights or Python needed. Running it again updates to the latest release.

& {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"   # the progress bar makes downloads much slower in Windows PowerShell
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $url = "https://github.com/apinanaivot/LegionNotch/releases/latest/download/LegionNotch.zip"
    $dir = Join-Path $env:LOCALAPPDATA "Programs\LegionNotch"
    $exe = Join-Path $dir "LegionNotch.exe"
    $zip = Join-Path $env:TEMP "LegionNotch-$([guid]::NewGuid()).zip"

    Write-Host "Downloading LegionNotch..."
    Invoke-WebRequest $url -OutFile $zip -UseBasicParsing

    Get-Process LegionNotch -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }

    Write-Host "Installing to $dir"
    Expand-Archive $zip $dir -Force
    Remove-Item $zip -Force

    $lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "LegionNotch.lnk"
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = $exe
    $sc.WorkingDirectory = $dir
    $sc.Description = "System-stats bar shaped like the Legion notch"
    $sc.Save()

    Start-Process $exe
    Write-Host "LegionNotch is running. Hover the top of the screen; the gear opens settings (including Start with Windows)."
}
