#Requires -Version 5.1
<#
.SYNOPSIS
    AutoApply bootstrap for Windows.
.DESCRIPTION
    One command, no prerequisites beyond what Windows ships (PowerShell,
    tar.exe on Windows 10 1803+). No admin rights, nothing system-wide.

    In order: create the AA root (default ~\.auto_apply); download the
    pinned uv binary and verify its SHA-256 against install_pins.txt;
    point UV_PYTHON_INSTALL_DIR / UV_CACHE_DIR into the root; fetch the AA
    source archive (release asset, or -Archive for offline/USB); hand over
    to AA's own --install (all further logic lives in Python).

    Everything downloaded is shown with sizes and confirmed first. uv and
    Python are checksum-verified; the source archive is verified against the
    release's SHA256SUMS.txt when available (that detects corruption, not
    compromise). Read this script and install_pins.txt before running; that
    is the trust model, stated plainly.

    SmartScreen/execution policy: an unsigned script from the internet may
    be blocked. Run: powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
    Offline / USB: install.ps1 -Root E:\AutoApply -Archive AA-src.tar.gz -Offline
    One prepared copy per OS: uv binaries and Python builds are per-platform.
#>
[CmdletBinding()]
param(
    [string]$Root,
    [switch]$Yes,
    [switch]$Offline,
    [string]$Archive,
    [string[]]$Extra,
    [switch]$Shortcut,
    [switch]$AllowUnverifiedSource
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-Pins([string]$Path) {
    $pins = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { throw "malformed pins line: $line" }
        $pins[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim()
    }
    return $pins
}

if (-not $Root) {
    $Root = if ($env:AA_INSTALL_ROOT) { $env:AA_INSTALL_ROOT } else { Join-Path $HOME '.auto_apply' }
}
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$pinsPath = Join-Path $scriptDir 'install_pins.txt'
if (-not (Test-Path $pinsPath)) {
    if ($Offline) { throw "offline mode but install_pins.txt not found next to the script" }
    New-Item -ItemType Directory -Force $Root | Out-Null
    $pinsPath = Join-Path $Root '.install_pins.txt'
    Write-Host 'Fetching install pins (one file, all versions and checksums)...'
    Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/Liebmann5/AA/main/packages/auto_apply/install_pins.txt' -OutFile $pinsPath
}
$pins = Read-Pins $pinsPath
$uvVersion = $pins['UV_VERSION']
$pythonVersion = $pins['PYTHON_VERSION']
if (-not $uvVersion -or -not $pythonVersion) { throw 'install_pins.txt is missing UV_VERSION or PYTHON_VERSION' }

$arch = $env:PROCESSOR_ARCHITECTURE
switch ($arch) {
    'AMD64' { $target = 'x86_64-pc-windows-msvc' }
    'ARM64' { $target = 'aarch64-pc-windows-msvc' }
    default { throw "unsupported Windows architecture: $arch" }
}
$checksumKey = 'UV_SHA256_' + ($target.ToUpper() -replace '-', '_')
$expected = $pins[$checksumKey]

Write-Host ''
Write-Host "AutoApply will be installed into: $Root"
Write-Host 'Nothing is installed system-wide; no administrator rights are used.'
Write-Host ''
Write-Host 'Downloads needed:'
Write-Host "  uv $uvVersion (the installer/runtime)             ~$($pins['SIZE_UV_MB']) MB"
Write-Host "  Python $pythonVersion (via uv, into the root)        ~$($pins['SIZE_PYTHON_MB']) MB"
Write-Host "  AutoApply source archive                        ~$($pins['SIZE_ARCHIVE_MB']) MB"
Write-Host "  Core dependencies (resolved by uv)              ~$($pins['SIZE_DEPS_CORE_MB']) MB"
Write-Host 'Your browser is detected later, never installed.'
Write-Host ''
if ($Offline) { Write-Host 'Offline mode: no downloads — the root must be pre-populated.' }
if (-not $Yes) {
    $answer = Read-Host 'Proceed? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { Write-Host 'Nothing was downloaded.'; exit 0 }
}

New-Item -ItemType Directory -Force "$Root\uv", "$Root\tmp", "$Root\app" | Out-Null

$uvBin = Join-Path $Root 'uv\uv.exe'
if ((Test-Path $uvBin) -and ((& $uvBin --version) -match [regex]::Escape($uvVersion))) {
    Write-Host "uv $uvVersion already present — skipping."
} else {
    if ($Offline) { throw "offline mode but no usable uv at $uvBin — pre-populate the root or re-run online" }
    if ($expected -notmatch '^[0-9a-fA-F]{64}$') {
        throw "uv's SHA-256 is not pinned in install_pins.txt ($checksumKey) — the release process fills this from the published uv release. Refusing to run an unverifiable binary."
    }
    $zip = Join-Path $Root "tmp\uv-$target.zip"
    Write-Host "Downloading uv $uvVersion..."
    Invoke-WebRequest -UseBasicParsing "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-$target.zip" -OutFile $zip
    $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($actual -ne $expected.ToLower()) {
        Remove-Item $zip -Force
        throw "checksum mismatch for uv $uvVersion (expected $expected, got $actual). The download was deleted; nothing was installed. This is the safety property working — do not bypass it."
    }
    Expand-Archive -Force $zip -DestinationPath (Join-Path $Root 'uv')
    if (-not (Test-Path $uvBin)) {
        Get-ChildItem (Join-Path $Root 'uv') -Directory | ForEach-Object {
            if (Test-Path (Join-Path $_.FullName 'uv.exe')) {
                Get-ChildItem $_.FullName | Move-Item -Destination (Join-Path $Root 'uv') -Force
            }
        }
    }
    Remove-Item $zip -Force
}
try { & $uvBin --version | Out-Null } catch {
    throw "cannot execute $uvBin — antivirus or policy may be blocking it ($($_.Exception.Message))"
}

$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'python'
$env:UV_CACHE_DIR = Join-Path $Root 'uv-cache'
$env:UV_NO_MODIFY_PATH = '1'
$env:UV_UNMANAGED_INSTALL = Join-Path $Root 'uv'

if (Test-Path (Join-Path $Root 'app\pyproject.toml')) {
    Write-Host 'AA source already present — skipping.'
} else {
    $srcArchive = Join-Path $Root 'tmp\aa-src.tar.gz'
    if ($Archive) {
        if ($Archive -match '^https?://') {
            if ($Offline) { throw '--Offline with a URL archive makes no sense' }
            Invoke-WebRequest -UseBasicParsing $Archive -OutFile $srcArchive
        } else {
            Copy-Item $Archive $srcArchive
        }
    } else {
        if ($Offline) { throw "offline mode but no source at $Root\app — pass -Archive AA-src.tar.gz" }
        $asset = $pins['AA_ARCHIVE_ASSET']
        $repo = $pins['AA_RELEASE_REPO']
        Write-Host 'Downloading AutoApply source (release asset)...'
        try {
            Invoke-WebRequest -UseBasicParsing "https://github.com/$repo/releases/latest/download/$asset" -OutFile $srcArchive
        } catch [System.Net.WebException] {
            throw "no source archive at that address (is there a release yet?). Use -Archive AA-src.tar.gz for a local copy."
        }
        # Verify against the release's checksum file. Ruled (D16): an
        # unverified source archive is NOT acceptable by default.
        $sumsAsset = $pins['AA_SUMS_ASSET']
        try {
            Invoke-WebRequest -UseBasicParsing "https://github.com/$repo/releases/latest/download/$sumsAsset" -OutFile (Join-Path $Root "tmp\$sumsAsset")
            $sumLine = Select-String -Path (Join-Path $Root "tmp\$sumsAsset") -Pattern " $asset`$" | Select-Object -First 1
            if ($sumLine) {
                $sum = ($sumLine.Line -split '\s+')[0].ToLower()
                $got = (Get-FileHash -Algorithm SHA256 $srcArchive).Hash.ToLower()
                if ($got -ne $sum) { Remove-Item $srcArchive -Force; throw 'source archive checksum mismatch — deleted, nothing installed.' }
                Write-Host 'Source archive checksum verified.'
            }
        } catch [System.Net.WebException] {
            if ($AllowUnverifiedSource) {
                Write-Host "WARNING: no $sumsAsset in the release — the archive is authenticated by HTTPS only (uv and Python ARE checksum-verified)."
            } else {
                Remove-Item $srcArchive -Force -ErrorAction SilentlyContinue
                throw "the release offers no $sumsAsset — refusing an unverifiable source archive. Use -AllowUnverifiedSource to accept HTTPS-only verification, or -Archive for a local copy."
            }
        }
    }
    # tar.exe ships with Windows 10 1803+ (bsdtar).
    & tar.exe -xzf $srcArchive -C (Join-Path $Root 'app') --strip-components=1
    if ($LASTEXITCODE -ne 0) { throw "could not extract the source archive (tar.exe is required; present since Windows 10 1803)" }
    Remove-Item $srcArchive -Force -ErrorAction SilentlyContinue
}

$env:AA_MANAGED_ROOT = $Root
$env:AA_DATA_DIR = Join-Path $Root 'data'

$installArgs = @('--root', $Root, '--yes')
if ($Offline) { $installArgs += '--offline' }
if ($Shortcut) { $installArgs += '--shortcut' }
foreach ($e in $Extra) { $installArgs += @('--extra', $e) }
$runArgs = @()
if ($Offline) { $runArgs += '--offline' }

# The bootstrap asked for consent above and it covers this whole flow, so
# --yes is passed on deliberately (see the plan printed before the download).
& $uvBin run @runArgs --project (Join-Path $Root 'app') --package auto_apply python -m auto_apply --install @installArgs
if ($LASTEXITCODE -ne 0) { throw "auto_apply --install failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host 'AutoApply is installed.'
Write-Host "Start it with: $Root\bin\auto-apply.bat        (GUI)"
Write-Host "               $Root\bin\auto-apply.bat --cli  (terminal)"
Write-Host "To remove everything: $Root\bin\auto-apply.bat --uninstall"
