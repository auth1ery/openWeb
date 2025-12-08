# build-and-sign.ps1
# ------------------
# Builds openWeb9.py and signs the resulting EXE.
# Nothing malicious: just build and sign.

$pythonFile = "openWeb10.py"
$outputDir = "dist"
$thumbprint = "ED3F76C0991BE3C49EB002D15D1FE419BFA30195"
$timestampUrl = "http://timestamp.digicert.com"
$signtoolPath = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"

Write-Host "`n[1/3] Checking PyInstaller..." -ForegroundColor Cyan
python -m pip show pyinstaller > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller not found - installing..." -ForegroundColor Yellow
    python -m pip install pyinstaller
}

Write-Host "`n[2/3] Building EXE..." -ForegroundColor Cyan
python -m PyInstaller $pythonFile --clean --noconsole --onefile --icon=openweb.ico

# Wait briefly to ensure file system updates are flushed
Start-Sleep -Seconds 2

# Automatically find the latest EXE in the dist folder
if (-not (Test-Path $outputDir)) {
    Write-Host "Build failed or dist folder not found." -ForegroundColor Red
    exit 1
}

$exePath = Get-ChildItem -Path $outputDir -Filter "*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $exePath) {
    Write-Host "Build failed or EXE not found. Check for build errors." -ForegroundColor Red
    exit 1
}

$exePath = $exePath.FullName
Write-Host "`nFound EXE: $exePath" -ForegroundColor Yellow

Write-Host "`n[3/3] Signing EXE..." -ForegroundColor Cyan
if (-not (Test-Path $signtoolPath)) {
    Write-Host "signtool.exe not found! Please install Windows SDK and update the path in this script." -ForegroundColor Red
    exit 1
}

& "$signtoolPath" sign /fd SHA256 /sha1 $thumbprint /tr $timestampUrl /td SHA256 $exePath

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nBuild and signing completed successfully!" -ForegroundColor Green
    Write-Host "Output: $exePath"
} else {
    Write-Host "`nSigning failed. Check your certificate thumbprint or SDK path." -ForegroundColor Red
}

