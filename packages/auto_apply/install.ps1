#Requires -Version 5.1
<#
.SYNOPSIS
    AutoApply bootstrap for Windows.
.DESCRIPTION
    One command, no prerequisites beyond what Windows ships (PowerShell 5.1).
    No admin rights, nothing system-wide.

    In order: create the AA root (default ~\.auto_apply); download the
    pinned uv binary and verify its SHA-256 against install_pins.txt;
    point UV_PYTHON_INSTALL_DIR / UV_CACHE_DIR into the root; get the AA
    source; hand over to AA's own --install (all further logic lives in
    Python).

    Where the source comes from, in order:
      1. -Archive FILE_OR_URL (offline/USB copies);
      2. the folder this script sits in, when it is inside an AA download
         or checkout (the usual case: someone downloaded the ZIP, extracted
         it and double-clicked INSTALL-WINDOWS.bat) - copied, no download;
      3. the latest GitHub release asset, verified against SHA256SUMS.txt.

    Everything downloaded is shown with sizes and confirmed first. uv and
    Python are checksum-verified; the release archive is verified against the
    release's SHA256SUMS.txt (that detects corruption, not compromise). Read
    this script and install_pins.txt before running; that is the trust model,
    stated plainly.

    This file must stay pure ASCII. Windows PowerShell 5.1 reads a script
    without a byte-order mark as ANSI, so a single UTF-8 em dash becomes three
    characters, one of them a curly quote that ends a string early and breaks
    the whole parse (measured 2026-10-07 on a stock Windows 11 PC).
    tests/architecture/test_installer_portability.py enforces it.

    Easiest: double-click INSTALL-WINDOWS.bat at the top of the download.
    By hand: powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
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
    [switch]$AllowUnverifiedSource,
    [string]$Python
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 redraws a progress bar for every downloaded chunk,
# which makes Invoke-WebRequest many times slower on low-end machines.
$ProgressPreference = 'SilentlyContinue'
# Older Windows 10 builds default to TLS 1.0/1.1, which GitHub refuses.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

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

# A local AA tree is used only when this script runs from a file inside one
# (never when piped through iex, where there is no script path).
$localRepo = $null
if ($PSScriptRoot -and -not $Archive) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    if ((Test-Path (Join-Path $candidate 'pyproject.toml')) -and
        (Test-Path (Join-Path $PSScriptRoot 'src\auto_apply\__main__.py'))) {
        $localRepo = $candidate.TrimEnd('\')
        $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
        if ($fullRoot.StartsWith($localRepo + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "the install folder ($fullRoot) is inside the downloaded AutoApply folder ($localRepo). Choose a -Root outside it."
        }
    }
}

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
if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }  # 32-bit PowerShell on 64-bit Windows
switch ($arch) {
    'AMD64' { $target = 'x86_64-pc-windows-msvc' }
    'ARM64' { $target = 'aarch64-pc-windows-msvc' }
    default { throw "unsupported Windows architecture: $arch (AutoApply needs 64-bit Windows)" }
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
Write-Host '    - only if this computer has no suitable Python; one already installed is'
Write-Host '      used as it is, and AutoApply never changes or removes it.'
if ($localRepo) {
    Write-Host "  AutoApply source                                none - copied from $localRepo"
} else {
    Write-Host "  AutoApply source archive                        ~$($pins['SIZE_ARCHIVE_MB']) MB"
}
Write-Host "  Core dependencies (resolved by uv)              ~$($pins['SIZE_DEPS_CORE_MB']) MB"
Write-Host 'Your browser is detected later, never installed.'
Write-Host 'If AutoApply is already installed and running, close it first.'
if ($Shortcut) { Write-Host 'A shortcut file named AutoApply is added to your Start-menu Programs folder (uninstall removes it).' }
Write-Host ''
if ($Offline) { Write-Host 'Offline mode: no downloads - the root must be pre-populated.' }
if (-not $Yes) {
    $answer = Read-Host 'Proceed? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { Write-Host 'Nothing was downloaded.'; exit 0 }
}

New-Item -ItemType Directory -Force "$Root\uv", "$Root\tmp", "$Root\app" | Out-Null

$uvBin = Join-Path $Root 'uv\uv.exe'
if ((Test-Path $uvBin) -and ((& $uvBin --version) -match [regex]::Escape($uvVersion))) {
    Write-Host "uv $uvVersion already present - skipping."
} else {
    if ($Offline) { throw "offline mode but no usable uv at $uvBin - pre-populate the root or re-run online" }
    if ($expected -notmatch '^[0-9a-fA-F]{64}$') {
        throw "uv's SHA-256 is not pinned in install_pins.txt ($checksumKey) - the release process fills this from the published uv release. Refusing to run an unverifiable binary."
    }
    $zip = Join-Path $Root "tmp\uv-$target.zip"
    Write-Host "Downloading uv $uvVersion..."
    Invoke-WebRequest -UseBasicParsing "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-$target.zip" -OutFile $zip
    $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($actual -ne $expected.ToLower()) {
        Remove-Item $zip -Force
        throw "checksum mismatch for uv $uvVersion (expected $expected, got $actual). The download was deleted; nothing was installed. This is the safety property working - do not bypass it."
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
    throw "cannot execute $uvBin - antivirus or policy may be blocking it ($($_.Exception.Message))"
}

$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'python'
$env:UV_CACHE_DIR = Join-Path $Root 'uv-cache'
$env:UV_NO_MODIFY_PATH = '1'
$env:UV_UNMANAGED_INSTALL = Join-Path $Root 'uv'
# The installer itself runs from a throwaway environment in the root's tmp
# folder, so AA's own environment (app\.venv) can be built on whichever
# Python AA chooses (python_choice.py) without replacing the interpreter
# that is running the installer. Inherited settings that would redirect it
# are cleared.
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Root 'tmp\bootstrap-env'
foreach ($name in 'UV_PYTHON', 'UV_PYTHON_PREFERENCE', 'VIRTUAL_ENV') {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
# Any Python 3.10+ already on the computer can run the installer. Only when
# there is none does uv download one - the pinned version, so the same
# download also serves as AA's own Python and is never fetched twice.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $uvBin python find '>=3.10' 2>$null | Out-Null
$haveHostPython = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap
if (-not $haveHostPython) {
    if ($Offline) { throw "offline mode and no Python 3.10+ on this computer or in $Root\python" }
    $env:UV_PYTHON = $pythonVersion
}

$appDir = Join-Path $Root 'app'
# Installing from a download or an archive you passed means "this version":
# the previous AutoApply files are replaced (its environment, .venv, is kept
# and repaired), so running a newer download's installer upgrades.
if (($localRepo -or $Archive) -and (Test-Path (Join-Path $appDir 'pyproject.toml'))) {
    Write-Host 'Replacing the previous AutoApply files with this version...'
    Get-ChildItem -LiteralPath $appDir -Force | Where-Object { $_.Name -ne '.venv' } | ForEach-Object {
        $env:AA_REPLACE_TARGET = $_.FullName
        if ($_.PSIsContainer) { & cmd.exe /d /c 'rmdir /s /q "%AA_REPLACE_TARGET%"' | Out-Null }
        else { Remove-Item -LiteralPath $_.FullName -Force }
    }
}
if (Test-Path (Join-Path $appDir 'pyproject.toml')) {
    Write-Host 'AA source already present - skipping.'
} elseif ($localRepo) {
    Write-Host "Copying AutoApply from $localRepo..."
    # A git checkout: copy exactly what git tracks plus new files it does not
    # ignore - never ignored local data (dev_data profiles, logs, caches,
    # .venv). A ZIP download has no .git and holds only repository files.
    $files = $null
    if ((Test-Path (Join-Path $localRepo '.git')) -and (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $prevEnc = $null
        try { $prevEnc = [Console]::OutputEncoding; [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
        $listing = & git.exe -C $localRepo -c core.quotepath=off ls-files --cached --others --exclude-standard 2>$null
        $gitOk = ($LASTEXITCODE -eq 0)
        if ($prevEnc) { try { [Console]::OutputEncoding = $prevEnc } catch { } }
        $ErrorActionPreference = $prevEap
        if ($gitOk) { $files = @($listing | Where-Object { $_ }) }
    }
    if ($files) {
        foreach ($rel in $files) {
            $from = Join-Path $localRepo $rel
            if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { continue }  # deleted, not yet committed
            $to = Join-Path $appDir $rel
            New-Item -ItemType Directory -Force (Split-Path $to -Parent) | Out-Null
            Copy-Item -LiteralPath $from -Destination $to -Force
        }
    } else {
        # robocopy ships with every Windows. Exit codes 0-7 mean success.
        & robocopy.exe $localRepo $appDir /E /XD .git .venv __pycache__ .mypy_cache .pytest_cache .ruff_cache .hypothesis node_modules dev_data /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "could not copy the AutoApply files into $appDir (robocopy exit code $LASTEXITCODE)" }
        $global:LASTEXITCODE = 0
    }
} else {
    $srcArchive = Join-Path $Root 'tmp\aa-src.tar.gz'
    if ($Archive) {
        if ($Archive -match '^https?://') {
            if ($Offline) { throw '-Offline with a URL archive makes no sense' }
            Invoke-WebRequest -UseBasicParsing $Archive -OutFile $srcArchive
        } else {
            Copy-Item $Archive $srcArchive
        }
    } else {
        if ($Offline) { throw "offline mode but no source at $appDir - pass -Archive AA-src.tar.gz" }
        $asset = $pins['AA_ARCHIVE_ASSET']
        $repo = $pins['AA_RELEASE_REPO']
        Write-Host 'Downloading AutoApply source (release asset)...'
        try {
            Invoke-WebRequest -UseBasicParsing "https://github.com/$repo/releases/latest/download/$asset" -OutFile $srcArchive
        } catch {
            throw "no source archive at that address (is there a release yet?). Download the ZIP from https://github.com/$repo, extract it and double-click INSTALL-WINDOWS.bat, or use -Archive AA-src.tar.gz."
        }
        # Verify against the release's checksum file. Ruled (D16): an
        # unverified source archive is NOT acceptable by default.
        $sumsAsset = $pins['AA_SUMS_ASSET']
        $sumsPath = Join-Path $Root "tmp\$sumsAsset"
        $haveSums = $true
        try {
            Invoke-WebRequest -UseBasicParsing "https://github.com/$repo/releases/latest/download/$sumsAsset" -OutFile $sumsPath
        } catch { $haveSums = $false }
        if ($haveSums) {
            $sumLine = Select-String -Path $sumsPath -Pattern " $asset`$" | Select-Object -First 1
            if ($sumLine) {
                $sum = ($sumLine.Line -split '\s+')[0].ToLower()
                $got = (Get-FileHash -Algorithm SHA256 $srcArchive).Hash.ToLower()
                if ($got -ne $sum) { Remove-Item $srcArchive -Force; throw 'source archive checksum mismatch - deleted, nothing installed.' }
                Write-Host 'Source archive checksum verified.'
            }
            Remove-Item $sumsPath -Force -ErrorAction SilentlyContinue
        } elseif ($AllowUnverifiedSource) {
            Write-Host "WARNING: no $sumsAsset in the release - the archive is authenticated by HTTPS only (uv and Python ARE checksum-verified)."
        } else {
            Remove-Item $srcArchive -Force -ErrorAction SilentlyContinue
            throw "the release offers no $sumsAsset - refusing an unverifiable source archive. Use -AllowUnverifiedSource to accept HTTPS-only verification, or -Archive for a local copy."
        }
    }
    # tar.exe ships with Windows 10 1803+ (bsdtar).
    & tar.exe -xzf $srcArchive -C $appDir --strip-components=1
    if ($LASTEXITCODE -ne 0) { throw "could not extract the source archive (tar.exe is required; present since Windows 10 1803)" }
    Remove-Item $srcArchive -Force -ErrorAction SilentlyContinue
}

$env:AA_MANAGED_ROOT = $Root
$env:AA_DATA_DIR = Join-Path $Root 'data'

$installArgs = @('--root', $Root, '--yes')
if ($Offline) { $installArgs += '--offline' }
if ($Shortcut) { $installArgs += '--shortcut' }
if ($Python) { $installArgs += @('--python', $Python) }
foreach ($e in @($Extra | Where-Object { $_ })) { $installArgs += @('--extra', $e) }
$runArgs = @()
if ($Offline) { $runArgs += '--offline' }

# The bootstrap asked for consent above and it covers this whole flow, so
# --yes is passed on deliberately (see the plan printed before the download).
& $uvBin run --no-dev @runArgs --project $appDir --package auto_apply python -m auto_apply --install @installArgs
if ($LASTEXITCODE -ne 0) { throw "auto_apply --install failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host 'AutoApply is installed.'
if ($localRepo) { Write-Host "You can now delete the downloaded folder ($localRepo) - AutoApply no longer needs it." }
Write-Host "Start it with: & `"$Root\bin\auto-apply.bat`"        (GUI)"
Write-Host "               & `"$Root\bin\auto-apply.bat`" --cli  (terminal)"
Write-Host "To remove everything: & `"$Root\bin\auto-apply.bat`" --uninstall"
