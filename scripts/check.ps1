<#
.SYNOPSIS
  Backpressure-Check: ruff check, ruff format --check, pytest -x -q.
  Erfolg: je Stufe nur "OK-Haken <stufe>". Fehler: "X <stufe>" + volle Ausgabe der Stufe.
.PARAMETER Hook
  Modus fuer den Claude-Code-Stop-Hook: bei Erfolg komplett still,
  bei Fehler alles auf stderr und Exit-Code 2.
#>
param([switch]$Hook)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONUTF8 = '1'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

$ok = [char]0x2713    # Haken
$fail = [char]0x2717  # Kreuz

$stages = @(
    @{ Name = 'ruff check';  Args = @('-m', 'ruff', 'check', '.') },
    @{ Name = 'ruff format'; Args = @('-m', 'ruff', 'format', '--check', '.') },
    @{ Name = 'pytest';      Args = @('-m', 'pytest', '-x', '-q') }
)

$failed = $false
$report = New-Object System.Text.StringBuilder

foreach ($stage in $stages) {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        $stageArgs = $stage.Args
        & $py @stageArgs 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $tmp -Encoding utf8
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            if (-not $Hook) { Write-Output "$ok $($stage.Name)" }
        } else {
            $failed = $true
            $text = "$fail $($stage.Name) (exit $code)`n" + (Get-Content -Raw -Encoding utf8 $tmp)
            if ($Hook) { [void]$report.AppendLine($text) } else { Write-Output $text }
        }
    } finally {
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
}

if ($failed) {
    if ($Hook) {
        [Console]::Error.Write($report.ToString())
        exit 2
    }
    exit 1
}
exit 0
