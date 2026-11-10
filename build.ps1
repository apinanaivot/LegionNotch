# Builds dist\LegionNotch.zip: a standalone LegionNotch.exe with everything it needs (no Python required).
# Needs: pip install -r requirements.txt pyinstaller
Set-Location $PSScriptRoot

Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
python -m PyInstaller notchbar.pyw `
    --name LegionNotch `
    --onedir --windowed --noconfirm --clean `
    --exclude-module tkinter `
    --exclude-module unittest `
    --exclude-module PySide6.QtNetwork `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Qt translations aren't used
Remove-Item dist\LegionNotch\_internal\PySide6\translations -Recurse -Force -ErrorAction SilentlyContinue

Compress-Archive dist\LegionNotch\* dist\LegionNotch.zip -Force
"Built dist\LegionNotch.zip ({0:N1} MB)" -f ((Get-Item dist\LegionNotch.zip).Length / 1MB)
