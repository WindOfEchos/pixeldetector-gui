$ErrorActionPreference = "Stop"

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python -m PyInstaller --onefile --windowed --name PixelDetector pixeldetector_gui.py

"Built dist\PixelDetector.exe"
