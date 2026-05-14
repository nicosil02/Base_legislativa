# Registra una tarea programada en Windows que corre `python -m scraper.cli update`
# cada 2 horas. Logs en update.log (en la carpeta del proyecto).
#
# Uso (PowerShell elevado en la carpeta del repo):
#   .\scripts\install_schedule.ps1
#
# Para desregistrar:
#   .\scripts\install_schedule.ps1 -Uninstall

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [int]$IntervalHours = 2,
    [string]$TaskName = "BaseLegislativa-Update"
)

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tarea '$TaskName' desregistrada."
    } else {
        Write-Host "No existe la tarea '$TaskName'."
    }
    return
}

# Resolver rutas absolutas
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$python      = (Get-Command python).Source
$logFile     = Join-Path $projectRoot "update.log"

if (-not (Test-Path "$projectRoot\scraper\cli.py")) {
    Write-Error "No encontré scraper/cli.py en $projectRoot. ¿Estás corriendo el script desde la carpeta del repo?"
    return
}

# Comando completo a ejecutar (con redireccion de logs)
$cmd = "& '$python' -m scraper.cli update *>> '$logFile'"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`"" `
    -WorkingDirectory $projectRoot

# Trigger: cada N horas, indefinidamente, comenzando 5 minutos despues de ahora
$start = (Get-Date).AddMinutes(5)
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# Registrar bajo el usuario actual (no requiere admin si solo afecta al user)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U

# Borrar si ya existe
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Actualiza la DB de proyectos de ley del Congreso del Peru cada $IntervalHours h."

Write-Host ""
Write-Host "Tarea '$TaskName' registrada."
Write-Host "  - Proyecto:        $projectRoot"
Write-Host "  - Python:          $python"
Write-Host "  - Intervalo:       $IntervalHours h"
Write-Host "  - Primer disparo:  $start"
Write-Host "  - Logs:            $logFile"
Write-Host ""
Write-Host "Comandos utiles:"
Write-Host "  Ver tarea:      Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Correr ahora:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Ver logs:       Get-Content '$logFile' -Tail 50 -Wait"
Write-Host "  Desinstalar:    .\scripts\install_schedule.ps1 -Uninstall"
