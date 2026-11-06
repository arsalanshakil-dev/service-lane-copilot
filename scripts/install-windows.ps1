<#
.SYNOPSIS
  Installs and starts Service Lane Copilot on Windows (issue #67).

.DESCRIPTION
  Run it once to install; run it again any time to start the app. Finished steps are skipped.

    1. Checks for Git, Python 3.11+, Node.js 20.9+ and Ollama; offers to install missing ones with winget.
    2. Downloads the project (or updates it with -Update).
    3. Creates the Python environment and installs the backend packages.
    4. Asks for the Supabase URL and secret key and saves them only in backend\.env.
    5. Pulls the local AI models (qwen3.5:4b and qwen3:1.7b).
    6. Installs and builds the web app.
    7. Starts the API and the web app in two new windows and opens the browser.

  Everything listens on this computer only (127.0.0.1). Close the two server windows to stop the app.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-windows.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-windows.ps1 -Update
#>
[CmdletBinding()]
param(
    # Where to put the project when the script is not already inside it.
    [string]$InstallDir = (Join-Path $HOME "service-lane-copilot"),
    # Pull the latest code and rebuild.
    [switch]$Update,
    # Pull only the smaller, faster model (qwen3:1.7b).
    [switch]$SmallModelOnly,
    # Install and build, but do not start the servers.
    [switch]$NoStart,
    # Ask for the Supabase URL and key again even if backend\.env exists.
    [switch]$ResetKeys,
    [int]$WebPort = 3000
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoUrl = "https://github.com/arsalanshakil-dev/service-lane-copilot.git"
$ApiPort = 8000
$Models = if ($SmallModelOnly) { @("qwen3:1.7b") } else { @("qwen3.5:4b", "qwen3:1.7b") }

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Note($text) { Write-Host "    $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host ""; Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    $ollamaDir = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
    if ((Test-Path $ollamaDir) -and ($env:Path -notlike "*$ollamaDir*")) { $env:Path += ";$ollamaDir" }
}

function Confirm-Yes($question) {
    $answer = Read-Host "$question [Y/n]"
    return ($answer -eq "" -or $answer -match "^(y|yes)$")
}

function Install-WithWinget($name, $id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "$name is missing and winget is not available. Install $name yourself, then run this script again."
    }
    if (-not (Confirm-Yes "    $name is missing. Install it now with winget?")) {
        Fail "$name is required. Install it, then run this script again."
    }
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Fail "winget could not install $name (exit code $LASTEXITCODE)." }
    Refresh-Path
}

function Get-VersionFrom($text) {
    $m = [regex]::Match("$text", "(\d+)\.(\d+)(\.(\d+))?")
    if (-not $m.Success) { return $null }
    $patch = if ($m.Groups[4].Success) { [int]$m.Groups[4].Value } else { 0 }
    return New-Object Version ([int]$m.Groups[1].Value), ([int]$m.Groups[2].Value), $patch
}

function Find-Python {
    # Returns the command and arguments for a Python 3.11+ interpreter, or $null.
    foreach ($candidate in @("py -3.12", "py -3.13", "py -3.11", "py -3", "python")) {
        $c = $candidate -split " "
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $args_ = @($c | Select-Object -Skip 1)
        try { $out = & $c[0] @args_ --version 2>&1 } catch { continue }
        if ($LASTEXITCODE -ne 0) { continue }
        $v = Get-VersionFrom $out
        if ($v -and $v -ge [Version]"3.11.0") { return ,$c }
    }
    return $null
}

function Test-Url($url, $timeoutSec = 5) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
        return $r.StatusCode -lt 400
    } catch { return $false }
}

function Wait-Url($url, $seconds, $label) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url $url) { return $true }
        Start-Sleep -Seconds 2
    }
    Note "$label did not answer at $url within $seconds seconds."
    return $false
}

function Test-PortFree($port) {
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Loopback), $port
        $listener.Start()
        return $true
    } catch { return $false } finally { if ($listener) { $listener.Stop() } }
}

Write-Host "Service Lane Copilot installer" -ForegroundColor White
Write-Host "Synthetic demo data only. Everything runs on this computer." -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. prerequisites
Step "Checking prerequisites"
Refresh-Path

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Install-WithWinget "Git" "Git.Git" }
Ok "Git: $((git --version) -replace 'git version ', '')"

$python = Find-Python
if (-not $python) {
    Install-WithWinget "Python 3.12" "Python.Python.3.12"
    $python = Find-Python
    if (-not $python) { Fail "Python 3.11 or newer was not found after installing. Open a new PowerShell window and run this script again." }
}
$pyExe = $python[0]; $pyArgs = @($python | Select-Object -Skip 1)
Ok "Python: $(& $pyExe @pyArgs --version 2>&1)"

$nodeOk = $false
if (Get-Command node -ErrorAction SilentlyContinue) { $nodeOk = (Get-VersionFrom (node --version)) -ge [Version]"20.9.0" }
if (-not $nodeOk) {
    Install-WithWinget "Node.js LTS" "OpenJS.NodeJS.LTS"
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or (Get-VersionFrom (node --version)) -lt [Version]"20.9.0") {
        Fail "Node.js 20.9 or newer was not found after installing. Open a new PowerShell window and run this script again."
    }
}
Ok "Node.js: $(node --version)"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Install-WithWinget "Ollama" "Ollama.Ollama" }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Fail "Ollama was not found after installing. Open a new PowerShell window and run this script again." }
Ok "Ollama: installed"

# ---------------------------------------------------------------- 2. project files
Step "Getting the project"
$here = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { $null }
if ($here -and (Test-Path (Join-Path $here "backend\app\main.py"))) {
    $root = $here
    Ok "Using the project this script is in: $root"
} elseif (Test-Path (Join-Path $InstallDir "backend\app\main.py")) {
    $root = $InstallDir
    Ok "Found the project in $root"
} else {
    if ((Test-Path $InstallDir) -and (Get-ChildItem $InstallDir -Force | Select-Object -First 1)) {
        Fail "$InstallDir exists and is not empty. Choose another folder with -InstallDir."
    }
    git clone --depth 1 $RepoUrl $InstallDir
    if ($LASTEXITCODE -ne 0) { Fail "Could not download the project from $RepoUrl." }
    $root = $InstallDir
    Ok "Downloaded to $root"
}
if ($Update) {
    if (-not (Test-Path (Join-Path $root ".git"))) { Fail "-Update needs a Git checkout; $root is not one." }
    git -C $root pull --ff-only
    if ($LASTEXITCODE -ne 0) { Fail "Could not update the project. If you changed files in $root, undo those changes and try again." }
    Ok "Updated to the latest version"
}
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

# ---------------------------------------------------------------- 3. backend
Step "Setting up the Python API"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $pyExe @pyArgs -m venv (Join-Path $backend ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the Python environment." }
}
$reqFile = Join-Path $backend "requirements.txt"
$reqHash = (Get-FileHash $reqFile -Algorithm SHA256).Hash
$reqMarker = Join-Path $backend ".venv\.requirements-sha256"
if ($Update -or -not (Test-Path $reqMarker) -or (Get-Content $reqMarker -Raw).Trim() -ne $reqHash) {
    & $venvPy -m pip install --disable-pip-version-check --quiet --upgrade pip
    & $venvPy -m pip install --disable-pip-version-check --quiet -r $reqFile
    if ($LASTEXITCODE -ne 0) { Fail "Installing the Python packages failed. Check your internet connection and run the script again." }
    Set-Content -Path $reqMarker -Value $reqHash -Encoding ASCII
    Ok "Python packages installed"
} else {
    Ok "Python packages already installed"
}

# ---------------------------------------------------------------- 4. database keys
Step "Database connection"
$envFile = Join-Path $backend ".env"
if ($ResetKeys -or -not (Test-Path $envFile)) {
    Write-Host "    The app reads its demo data from a Supabase database."
    Write-Host "    Use the URL and secret key you were given privately. The key is saved only in backend\.env."
    do { $url = (Read-Host "    Supabase URL (https://....supabase.co)").Trim() } while ($url -notmatch "^https?://\S+$")
    do {
        $secure = Read-Host "    Supabase secret key (hidden)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    } while (-not $key)
    $lines = @(
        "# Written by scripts\install-windows.ps1. Keep this file private; never commit or share it.",
        "SUPABASE_URL=$url",
        "SUPABASE_SECRET_KEY=$key",
        "OLLAMA_TIMEOUT_SECONDS=600"
    )
    [IO.File]::WriteAllLines($envFile, $lines)
    $key = $null
    Ok "Saved backend\.env"
} else {
    Ok "backend\.env already exists (use -ResetKeys to enter new values)"
}

# ---------------------------------------------------------------- 5. local AI
Step "Local AI models (Ollama)"
if (-not (Test-Url "http://127.0.0.1:11434/api/tags")) {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    if (-not (Wait-Url "http://127.0.0.1:11434/api/tags" 60 "Ollama")) { Fail "Ollama did not start. Open the Ollama app, then run this script again." }
}
$installed = (ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split "\s+")[0] })
foreach ($model in $Models) {
    if ($installed -contains $model) { Ok "$model already installed"; continue }
    Note "Downloading $model (a few GB; this can take a while)..."
    ollama pull $model
    if ($LASTEXITCODE -ne 0) { Fail "Could not download $model. Check your internet connection and run the script again." }
    Ok "$model installed"
}

# ---------------------------------------------------------------- 6. web app
Step "Setting up the web app"
$lockHash = (Get-FileHash (Join-Path $frontend "package-lock.json") -Algorithm SHA256).Hash
$npmMarker = Join-Path $frontend "node_modules\.package-lock-sha256"
Push-Location $frontend
try {
    if (-not (Test-Path $npmMarker) -or (Get-Content $npmMarker -Raw).Trim() -ne $lockHash) {
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Fail "Installing the web app packages failed." }
        Set-Content -Path $npmMarker -Value $lockHash -Encoding ASCII
        Ok "Web packages installed"
    } else {
        Ok "Web packages already installed"
    }
    $head = if (Test-Path (Join-Path $root ".git")) { (git -C $root rev-parse HEAD).Trim() } else { "no-git" }
    $buildMarker = Join-Path $frontend ".next\.built-from"
    if (-not (Test-Path (Join-Path $frontend ".next\BUILD_ID")) -or -not (Test-Path $buildMarker) -or (Get-Content $buildMarker -Raw).Trim() -ne $head) {
        Note "Building the web app (one or two minutes)..."
        npm run build
        if ($LASTEXITCODE -ne 0) { Fail "Building the web app failed." }
        Set-Content -Path $buildMarker -Value $head -Encoding ASCII
        Ok "Web app built"
    } else {
        Ok "Web app already built"
    }
} finally { Pop-Location }

if ($NoStart) {
    Step "Installed. Run this script again to start the app."
    exit 0
}

# ---------------------------------------------------------------- 7. start
Step "Starting the app"
$apiUp = Test-Url "http://127.0.0.1:$ApiPort/api/health"
if (-not $apiUp) {
    if (-not (Test-PortFree $ApiPort)) { Fail "Port $ApiPort is used by another program. Close it, then run this script again." }
    $apiCmd = "`$Host.UI.RawUI.WindowTitle = 'Service Lane Copilot - API (close to stop)'; Set-Location '$backend'; & '$venvPy' -m uvicorn app.main:app --host 127.0.0.1 --port $ApiPort"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $apiCmd) | Out-Null
}
if (-not (Wait-Url "http://127.0.0.1:$ApiPort/api/health" 120 "The API")) {
    Fail "The API window shows the reason. Most often the Supabase URL or key is wrong: run this script with -ResetKeys."
}
$health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
Ok "API running: $($health.record_count) vehicle records in the database"

$webUrl = "http://127.0.0.1:$WebPort"
if (-not (Test-Url $webUrl)) {
    if (-not (Test-PortFree $WebPort)) { Fail "Port $WebPort is used by another program. Run this script with -WebPort 3001." }
    $webCmd = "`$Host.UI.RawUI.WindowTitle = 'Service Lane Copilot - Web app (close to stop)'; Set-Location '$frontend'; npx next start -H 127.0.0.1 -p $WebPort"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $webCmd) | Out-Null
}
if (-not (Wait-Url $webUrl 90 "The web app")) { Fail "The web app window shows the reason." }
Ok "Web app running at $webUrl"

Start-Process $webUrl
Write-Host ""
Write-Host "Service Lane Copilot is running at $webUrl" -ForegroundColor Green
Write-Host "  - Close the two 'Service Lane Copilot' windows to stop it."
Write-Host "  - Run this script again to start it later (it skips the install steps)."
Write-Host "  - The first AI answer can take 1-3 minutes while the model loads."
Write-Host "  - The demo guide is in $(Join-Path $root 'docs\guide\TESTER_GUIDE.md')"
