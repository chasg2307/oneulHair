$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$defaultAppName = "autoHair"
$appName = $defaultAppName
$confExamplePath = Join-Path $repoRoot "autohair.conf.example"
if (Test-Path $confExamplePath) {
    $inProjectSection = $false
    foreach ($line in Get-Content -Path $confExamplePath -Encoding UTF8) {
        $trimmed = ($line -as [string]).Trim()
        if ($trimmed -match "^\[.*\]$") {
            $inProjectSection = $trimmed.Equals("[project]", [System.StringComparison]::OrdinalIgnoreCase)
            continue
        }
        if ($inProjectSection -and $trimmed -match "^(?i)name\s*=\s*(.+)$") {
            $candidate = $Matches[1].Trim()
            if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                $appName = $candidate
            }
            break
        }
    }
}
$appName = ($appName -replace '[\\/:*?"<>|]', "_").Trim()
if ([string]::IsNullOrWhiteSpace($appName)) {
    $appName = $defaultAppName
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $createdVenv = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($pyArgs in @(
            @("-3.11", "-m", "venv", ".venv"),
            @("-3", "-m", "venv", ".venv"),
            @("-m", "venv", ".venv")
        )) {
            & py @pyArgs
            if ($LASTEXITCODE -eq 0) {
                $createdVenv = $true
                break
            }
        }
    }
    if (-not $createdVenv -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -m venv .venv
        if ($LASTEXITCODE -eq 0) {
            $createdVenv = $true
        }
    }
    if (-not $createdVenv) {
        throw "Python not found. Install Python 3.11+ (or any Python 3.x) on the build machine."
    }
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

& $venvPython -m PyInstaller main.py --noconfirm --clean --name $appName --onedir --console `
    --collect-all playwright `
    --collect-all gspread `
    --collect-all google.auth `
    --collect-all google.oauth2
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

# Edge-only runtime: remove Chrome reinstall helper scripts from bundle.
$chromeInstallScripts = Get-ChildItem -Path (Join-Path $repoRoot "dist\$appName\_internal\playwright\driver\package\bin") `
    -Filter "reinstall_chrome_*" -ErrorAction SilentlyContinue
if ($chromeInstallScripts) {
    $chromeInstallScripts | Remove-Item -Force
}

$releaseDir = Join-Path $repoRoot "release"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

$releaseAppDir = Join-Path $releaseDir $appName
if (Test-Path $releaseAppDir) {
    Remove-Item -Path $releaseAppDir -Recurse -Force
}

Copy-Item -Path (Join-Path $repoRoot "dist\$appName") -Destination $releaseDir -Recurse -Force
Copy-Item -Path (Join-Path $repoRoot "autohair.conf.example") -Destination (Join-Path $releaseDir "autohair.conf") -Force
Copy-Item -Path (Join-Path $repoRoot "run_release.bat") -Destination (Join-Path $releaseDir "run.bat") -Force

Write-Host ""
Write-Host "Build completed."
Write-Host "App name: $appName"
Write-Host "Release folder: $releaseDir"
Write-Host "Run command: .\release\run.bat"

