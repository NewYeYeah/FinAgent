param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ControlArgs
)

$ErrorActionPreference = "Stop"
$ScriptPath = Join-Path $PSScriptRoot "run_workbench_control.py"

if ($env:FINAGENT_PYTHON) {
    & $env:FINAGENT_PYTHON $ScriptPath @ControlArgs
    exit $LASTEXITCODE
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) {
    & $Python.Source $ScriptPath @ControlArgs
    exit $LASTEXITCODE
}

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
    & $PyLauncher.Source -3.11 $ScriptPath @ControlArgs
    exit $LASTEXITCODE
}

throw "Python 3.11+ was not found. Set FINAGENT_PYTHON or install Python/py launcher."
