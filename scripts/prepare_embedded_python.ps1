#Requires -Version 5.1
<#
.SYNOPSIS
  Download Windows embeddable Python, enable pip/site-packages, install backend deps.
  Output: <Repo>/runtime/python/python.exe (used by start_kairi.bat).

.PARAMETER Force
  Rebuild even if runtime/python already has deps marker.
#>
param(
  [switch]$Force,
  [string]$PythonVersion = "3.12.8"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Runtime = Join-Path $Root "runtime\python"
$Cache = Join-Path $Root "dist\py-embed-cache"
$Marker = Join-Path $Runtime ".kairi_deps_ok"
$Req = Join-Path $Root "backend\requirements.txt"

if (-not (Test-Path $Req)) { throw "Missing $Req" }

New-Item -ItemType Directory -Path $Cache -Force | Out-Null

$zipName = "python-$PythonVersion-embed-amd64.zip"
$zipPath = Join-Path $Cache $zipName
$url = "https://www.python.org/ftp/python/$PythonVersion/$zipName"

if ((Test-Path $Marker) -and -not $Force) {
  Write-Host "Embedded Python already prepared: $Runtime"
  Write-Host "Pass -Force to rebuild."
  exit 0
}

if ($Force -and (Test-Path $Runtime)) {
  Write-Host "==> Removing existing runtime\python"
  Remove-Item -Recurse -Force $Runtime
}

if (-not (Test-Path $zipPath)) {
  Write-Host "==> Downloading $url"
  Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
}

Write-Host "==> Extracting to $Runtime"
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
Expand-Archive -Path $zipPath -DestinationPath $Runtime -Force

# Enable site-packages for embeddable distribution (required for pip)
$pth = Get-ChildItem -Path $Runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "python*._pth not found in $Runtime" }
$verParts = $PythonVersion.Split(".")
$zipStem = "python$($verParts[0])$($verParts[1]).zip"
$pthBody = @"
$zipStem
.
Lib\site-packages
import site
"@
Set-Content -LiteralPath $pth.FullName -Value $pthBody -Encoding ASCII
Write-Host "==> Wrote $($pth.Name) with import site"

$py = Join-Path $Runtime "python.exe"
if (-not (Test-Path $py)) { throw "python.exe missing after extract" }

$getPip = Join-Path $Cache "get-pip.py"
if (-not (Test-Path $getPip)) {
  Write-Host "==> Downloading get-pip.py"
  Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
}

Write-Host "==> Installing pip"
& $py $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }

Write-Host "==> pip install -r backend/requirements.txt (this may take several minutes)"
& $py -m pip install --upgrade pip --no-warn-script-location
& $py -m pip install -r $Req --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }

$reqHash = (Get-FileHash -Path $Req -Algorithm SHA256).Hash
Set-Content -Path $Marker -Value $reqHash -Encoding ASCII

Write-Host ""
Write-Host "OK: Embedded Python ready at $Runtime"
Write-Host "Marker: $Marker"
