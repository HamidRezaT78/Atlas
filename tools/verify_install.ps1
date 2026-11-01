# Read-only check of the installed "Atlas Database Documentation" Claude Desktop extension.
# Does not connect to Oracle, read credentials, or change any file.
# Usage: powershell -ExecutionPolicy Bypass -File tools\verify_install.ps1

$expected = "3.0.0"
$expectedTools = 9
$dataRoot = Join-Path $env:LOCALAPPDATA "Claude-Data"
$ext = Get-ChildItem $dataRoot -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "Claude Extensions\local.mcpb.local.atlas-db-docs" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $ext) { Write-Output "FAIL  extension folder not found under $dataRoot"; exit 1 }
$manifest = Get-Content -Raw (Join-Path $ext "manifest.json") | ConvertFrom-Json
$server = Get-Content -Raw (Join-Path $ext "server\oracle_mcp.py")
$tools = ([regex]::Matches($server, '(?m)^@mcp\.tool\(\)\s*\r?\ndef (\w+)')).Count
$oradoc = Test-Path (Join-Path $ext "server\oradoc\queries.py")

$ok = $true
function Check($cond, $msg) { if ($cond) { Write-Output "OK    $msg" } else { Write-Output "FAIL  $msg"; $script:ok = $false } }
Write-Output "installed at: $ext"
Check ($manifest.version -eq $expected) "installed manifest version = $($manifest.version) (expected $expected)"
Check ($tools -eq $expectedTools) "tool functions in installed server = $tools (expected $expectedTools)"
Check $oradoc "oradoc package present in installed server"

$log = Join-Path $env:LOCALAPPDATA "Claude\logs\main.log"
$announce = Select-String -Path $log -Pattern 'announcing Atlas Database Documentation: (\d+) tool' -ErrorAction SilentlyContinue | Select-Object -Last 1
if ($announce) {
    $n = [int]$announce.Matches[0].Groups[1].Value
    Check ($n -eq $expectedTools) "last running-server announcement: $n tool(s) at $($announce.Line.Substring(0, 19))"
} else {
    Check $false "no running-server announcement found in main.log"
}
if ($ok) { Write-Output "RESULT: installed and running server expose version $expected" ; exit 0 }
Write-Output "RESULT: not yet updated"; exit 2
