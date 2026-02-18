$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else {
        throw "Python not found. Install Python 3.11+ on the build machine."
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment." }
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

& $venvPython -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

$edgeCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
)
$edgeExe = $edgeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $edgeExe) {
    throw "Microsoft Edge is not installed. Install Edge first, then run this script again."
}

& $venvPython -m PyInstaller main.py --noconfirm --clean --name oneulHair --onedir --console `
    --collect-all playwright `
    --collect-all gspread `
    --collect-all google.auth `
    --collect-all google.oauth2
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

# Edge-only runtime: remove Chrome reinstall helper scripts from bundle.
$chromeInstallScripts = Get-ChildItem -Path (Join-Path $repoRoot "dist\oneulHair\_internal\playwright\driver\package\bin") `
    -Filter "reinstall_chrome_*" -ErrorAction SilentlyContinue
if ($chromeInstallScripts) {
    $chromeInstallScripts | Remove-Item -Force
}

$releaseDir = Join-Path $repoRoot "release"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

Copy-Item -Path (Join-Path $repoRoot "dist\oneulHair") -Destination $releaseDir -Recurse -Force
Copy-Item -Path (Join-Path $repoRoot "oneulhair.conf.example") -Destination (Join-Path $releaseDir "oneulhair.conf") -Force
Copy-Item -Path (Join-Path $repoRoot "run_release.bat") -Destination (Join-Path $releaseDir "run.bat") -Force

Write-Host ""
Write-Host "Build completed."
Write-Host "Release folder: $releaseDir"
Write-Host "Run command: .\release\run.bat"
