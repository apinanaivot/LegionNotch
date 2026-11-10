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

    $fresh = -not (Test-Path $dir)

    # updating: stop the running copy and wait until Windows releases its files
    Get-Process LegionNotch -ErrorAction SilentlyContinue | Stop-Process -Force
    Wait-Process LegionNotch -Timeout 10 -ErrorAction SilentlyContinue
    for ($i = 0; (Test-Path $dir) -and $i -lt 20; $i++) {
        try { Remove-Item $dir -Recurse -Force } catch { Start-Sleep -Milliseconds 500 }
    }
    if (Test-Path $dir) { throw "Couldn't replace $dir. Close LegionNotch and run the installer again." }

    Write-Host "Installing to $dir"
    Expand-Archive $zip $dir -Force
    Remove-Item $zip -Force

    $lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "LegionNotch.lnk"
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = $exe
    $sc.WorkingDirectory = $dir
    $sc.Description = "System-stats bar shaped like the Legion notch"
    $sc.Save()

    # start with Windows: on for a fresh install; an update keeps whatever was chosen in settings
    $run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $had = $null -ne (Get-ItemProperty $run -Name NotchBar -ErrorAction SilentlyContinue)
    if ($fresh -or $had) { Set-ItemProperty $run -Name NotchBar -Value "`"$exe`"" }

    Start-Process $exe
    Write-Host "LegionNotch is installed and running."
}
