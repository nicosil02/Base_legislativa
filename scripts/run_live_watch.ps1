# Supervisor de `congreso_live.cli live-watch`: lo corre para siempre,
# reiniciandolo solo si se cae (crash, corte de red, lo que sea).
# `live-watch` en si mismo ya es un loop infinito (ver
# congreso_live/live_transcribe.py) - este wrapper es la ultima capa de
# resiliencia, para el caso de una excepcion no manejada que lo mate.
#
# Lo dispara el Programador de Tareas de Windows al iniciar sesion (ver
# install_live_watch.ps1) - correlo a mano solo para debug.

$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $projectRoot
$python = (Get-Command python).Source

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] arrancando live-watch ($python)..."
    & $python -u -m congreso_live.cli live-watch
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] live-watch termino (codigo $LASTEXITCODE) - reintento en 15s."
    Start-Sleep -Seconds 15
}
