# Dailybot CLI installer (Windows / PowerShell)
# Usage:
#   irm https://cli.dailybot.com/install.ps1 | iex
# or, with verification (recommended):
#   $script = irm https://cli.dailybot.com/install.ps1
#   $expected = irm https://cli.dailybot.com/install.ps1.sha256
#   # ... compute and compare hash, then iex $script
#
# This script mirrors install.sh: it tries the most isolated installer first
# (pipx), then uv, then pip --user as a fallback. It does NOT download a
# pre-built .exe today — the Linux/macOS binary path is platform-specific
# and the Windows variant is not yet built. Devs on Windows are expected to
# have Python 3.10+ on PATH (the same minimum the published wheel requires).

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$Package    = 'dailybot-cli'
$Command    = 'dailybot'
$MinPython  = [version]'3.10'

function Write-Info    { param([string]$msg) Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok      { param([string]$msg) Write-Host "==> $msg" -ForegroundColor Green }
function Write-Warn    { param([string]$msg) Write-Host "==> $msg" -ForegroundColor Yellow }
function Write-Err     { param([string]$msg) Write-Host "Error: $msg" -ForegroundColor Red }

function Has-Cmd {
    param([string]$name)
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Find-Python {
    # Pick the first interpreter on PATH that satisfies $MinPython.
    # Tries `python`, `python3`, and the Windows `py` launcher (in that order).
    $candidates = @('python', 'python3')
    foreach ($name in $candidates) {
        if (-not (Has-Cmd $name)) { continue }
        $verLine = & $name -c 'import sys; print(".".join(map(str,sys.version_info[:3])))' 2>$null
        if (-not $verLine) { continue }
        try {
            $ver = [version]$verLine
            if ($ver -ge $MinPython) { return @{ Cmd = $name; Args = @(); Version = $ver } }
        } catch { continue }
    }
    if (Has-Cmd 'py') {
        $verLine = & py -3 -c 'import sys; print(".".join(map(str,sys.version_info[:3])))' 2>$null
        if ($verLine) {
            try {
                $ver = [version]$verLine
                if ($ver -ge $MinPython) { return @{ Cmd = 'py'; Args = @('-3'); Version = $ver } }
            } catch {}
        }
    }
    return $null
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$ExtraArgs
    )
    & $Python.Cmd @($Python.Args + $ExtraArgs)
}

function Try-Pipx {
    param([hashtable]$Python)
    if (Has-Cmd 'pipx') {
        Write-Info "Installing with pipx..."
        & pipx install $Package --force
        return $?
    }
    # pipx not on PATH — try invoking it via Python module if installed
    Invoke-Python $Python @('-m', 'pipx', '--version') *>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Installing with python -m pipx..."
        Invoke-Python $Python @('-m', 'pipx', 'install', $Package, '--force')
        return $?
    }
    return $false
}

function Try-UvTool {
    if (Has-Cmd 'uv') {
        Write-Info "Installing with uv tool..."
        & uv tool install $Package --force
        return $?
    }
    return $false
}

function Try-PipUser {
    param([hashtable]$Python)
    Write-Info "Installing with pip --user..."
    Invoke-Python $Python @('-m', 'pip', 'install', '--user', '--upgrade', $Package)
    return $?
}

function Add-LocalBinToPath {
    # `pip install --user` and `pipx install` drop scripts under the user's
    # Python Scripts directory, which is not on PATH by default on Windows.
    # Resolve the active Python's user-site scripts dir and persist it in the
    # user's PATH (HKCU). Idempotent — won't add the same path twice.
    param([hashtable]$Python)
    $userScripts = Invoke-Python $Python @(
        '-c',
        "import site, os; p = os.path.join(os.path.dirname(site.getusersitepackages()), 'Scripts'); print(p)"
    )
    if (-not $userScripts) { return }
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([string]::IsNullOrEmpty($current)) { $current = '' }
    $segments = $current.Split(';') | Where-Object { $_ -ne '' }
    if ($segments -notcontains $userScripts) {
        $newPath = (@($segments) + $userScripts) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        $env:Path = "$env:Path;$userScripts"
        Write-Warn "Added $userScripts to your user PATH (effective in new shells)."
    }
}

# === Main =================================================================

Write-Info "Detecting Python..."
$py = Find-Python
if ($null -eq $py) {
    Write-Err "Python $MinPython or newer is required but was not found on PATH."
    Write-Host ""
    Write-Host "  Install Python from https://www.python.org/downloads/ (check 'Add Python to PATH')"
    Write-Host "  or via the Microsoft Store, then re-run this script."
    exit 1
}
Write-Ok "Found Python $($py.Version) ($($py.Cmd))"

$installed = $false

# 1. pipx (preferred — isolated venv, manages PATH)
if (-not $installed) {
    if (Try-Pipx -Python $py) { $installed = $true }
    else { Write-Warn "pipx not available, trying next method..." }
}

# 2. uv tool (fast alternative to pipx)
if (-not $installed -and (Try-UvTool)) { $installed = $true }

# 3. pip --user (fallback — works without pipx/uv)
if (-not $installed) {
    if (Try-PipUser -Python $py) { $installed = $true }
}

if (-not $installed) {
    Write-Err "All installation methods failed."
    Write-Host ""
    Write-Host "  Try manually:"
    Write-Host "    pipx install $Package"
    Write-Host "    # or"
    Write-Host "    pip install --user $Package"
    exit 1
}

# Make sure the install dir is on PATH for fresh shells.
Add-LocalBinToPath -Python $py

Write-Host ""
if (Has-Cmd $Command) {
    $ver = & $Command --version 2>&1
    Write-Ok "Dailybot CLI installed successfully! ($ver)"
} else {
    Write-Ok "Dailybot CLI installed successfully!"
    Write-Warn "The '$Command' command is not on your PATH yet."
    Write-Host "  Restart your shell or open a new PowerShell window, then re-run 'dailybot --version'."
}
Write-Host ""
Write-Host "  Get started:"
Write-Host "    dailybot login"
Write-Host "    dailybot --help"
Write-Host ""
