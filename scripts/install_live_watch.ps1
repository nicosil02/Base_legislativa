# Deja `live-watch` corriendo en background para siempre, arrancando
# solo al iniciar sesion de Windows - asi la transcripcion en vivo no
# depende de que alguien la dispare a mano cada vez.
#
# Usa la carpeta de Inicio de Windows (shell:startup), NO el Programador
# de Tareas: se probo con Task Scheduler (LogonType Interactive) primero
# y fallaba en este entorno (Register-ScheduledTask con S4U pedia admin;
# con Interactive se registraba pero el proceso disparado por el
# servicio de Task Scheduler nunca lograba adjuntarse a la sesion de
# escritorio activa, mientras que lanzar el MISMO comando a mano
# funcionaba perfecto). La carpeta de Inicio es el mecanismo nativo de
# Windows para "correr esto cuando ESTE usuario inicia sesion" - no
# depende del servicio de Task Scheduler ni de ningun permiso especial,
# solo escribe un acceso directo en una carpeta propia del usuario.
#
# Uso (PowerShell en la carpeta del repo):
#   .\scripts\install_live_watch.ps1
#
# Para desinstalar:
#   .\scripts\install_live_watch.ps1 -Uninstall

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$ShortcutName = "BaseLegislativa-LiveWatch.lnk"
)

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath  = Join-Path $startupFolder $ShortcutName

if ($Uninstall) {
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath -Force
        Write-Host "Acceso directo eliminado de la carpeta de Inicio."
    } else {
        Write-Host "No existe '$shortcutPath'."
    }
    return
}

$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$python      = (Get-Command python).Source
$runScript   = Join-Path $projectRoot "scripts\run_live_watch.ps1"
$logFile     = Join-Path $projectRoot "live_watch.log"

if (-not (Test-Path "$projectRoot\congreso_live\cli.py")) {
    Write-Error "No encontré congreso_live/cli.py en $projectRoot. ¿Estás corriendo esto desde la carpeta del repo?"
    return
}

# faster-whisper/imageio-ffmpeg pesan ~200MB y NO estan en
# requirements.txt a proposito (ver congreso_live/live_transcribe.py) -
# verificar que esten instalados en ESTE interprete antes de instalar
# nada, para no dejar un acceso directo que va a fallar siempre.
& $python -c "import faster_whisper, imageio_ffmpeg" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "faster-whisper / imageio-ffmpeg no estan instalados en $python."
    Write-Warning "Corré primero: & '$python' -m pip install faster-whisper imageio-ffmpeg"
    return
}

# -Command (no -File): con -File, todo lo que va despues del path del
# script se pasa como ARGUMENTO al script en vez de interpretarse como
# redireccion - "*>> logFile" nunca redirigia nada con -File (bug real
# encontrado al probar esto en vivo 2026-09-14, mismo problema tanto
# via Task Scheduler como via el acceso directo).
$cmd = "& '$runScript' *>> '$logFile'"

$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -Command `"$cmd`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7  # minimizada
$shortcut.Description = "Transcribe en vivo (Pleno + comisiones) automaticamente mientras el Congreso este transmitiendo."
$shortcut.Save()

Write-Host ""
Write-Host "Acceso directo instalado en la carpeta de Inicio."
Write-Host "  - Proyecto:  $projectRoot"
Write-Host "  - Python:    $python"
Write-Host "  - Atajo:     $shortcutPath"
Write-Host "  - Logs:      $logFile"
Write-Host ""
Write-Host "Arranca solo la proxima vez que inicies sesion en Windows. Para"
Write-Host "probarlo AHORA sin reiniciar sesion, doble click en el archivo:"
Write-Host "  $shortcutPath"
Write-Host ""
Write-Host "Comandos utiles:"
Write-Host "  Ver logs:     Get-Content '$logFile' -Tail 50 -Wait"
Write-Host "  Desinstalar:  .\scripts\install_live_watch.ps1 -Uninstall"
