# Installs the Krita MCP bridge plugin into Krita and turns it on.
# Run it with Krita closed (Krita rewrites its settings file when it quits).
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot 'plugin'
$pykrita = Join-Path $env:APPDATA 'krita\pykrita'
$kritarc = Join-Path $env:LOCALAPPDATA 'kritarc'

if (Get-Process -Name krita -ErrorAction SilentlyContinue) {
    Write-Host 'Krita is running. Close it first, then run this again.' -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Force $pykrita | Out-Null
$dest = Join-Path $pykrita 'krita_mcp'
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
Copy-Item -Recurse (Join-Path $src 'krita_mcp') $dest
Copy-Item -Force (Join-Path $src 'kritapykrita_krita_mcp.desktop') $pykrita
Write-Host "Plugin copied to $dest"

# Enable it: [python] enable_krita_mcp=true in kritarc
$utf8 = New-Object System.Text.UTF8Encoding($false)
$lines = @()
if (Test-Path $kritarc) {
    Copy-Item -Force $kritarc "$kritarc.before-krita-mcp" -ErrorAction SilentlyContinue
    $lines = [System.IO.File]::ReadAllLines($kritarc, $utf8)
}
$out = New-Object System.Collections.Generic.List[string]
$inPython = $false; $done = $false; $hasSection = $false
foreach ($l in $lines) {
    if ($l -match '^\[(.+)\]$') {
        if ($inPython -and -not $done) { $out.Add('enable_krita_mcp=true'); $done = $true }
        $inPython = ($Matches[1] -eq 'python')
        if ($inPython) { $hasSection = $true }
    }
    elseif ($inPython -and $l -match '^enable_krita_mcp=') { $l = 'enable_krita_mcp=true'; $done = $true }
    $out.Add($l)
}
if ($inPython -and -not $done) { $out.Add('enable_krita_mcp=true'); $done = $true }
if (-not $hasSection) { $out.Add(''); $out.Add('[python]'); $out.Add('enable_krita_mcp=true') }
[System.IO.File]::WriteAllLines($kritarc, $out, $utf8)
Write-Host 'Plugin enabled in Krita settings.'
Write-Host 'Start Krita: the bridge listens on 127.0.0.1:9877 (Tools > Scripts > Krita MCP (Claude): status).' -ForegroundColor Green
