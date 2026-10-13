# Installatore automatico: Python + MetaTrader 5 + copiatore segnali + avvio automatico.
# Si lancia con un doppio clic su INSTALLA.bat (oppure CONFIGURA.bat per rifare solo la configurazione).

param([switch]$Reconfigure)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$InstallDir = 'C:\SeersCopier'
$TaskName = 'SeersCopier'
$PythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$Mt5Url = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'
$AutologonUrl = 'https://download.sysinternals.com/files/AutoLogon.zip'

# --- Riavvio come amministratore se serve
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $argsList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($Reconfigure) { $argsList += ' -Reconfigure' }
    Start-Process powershell -ArgumentList $argsList -Verb RunAs
    exit
}

function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK - $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    ATTENZIONE - $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host "`nERRORE: $text" -ForegroundColor Red
    Read-Host "`nPremi INVIO per chiudere"
    exit 1
}

function Stop-Bot {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='cmd.exe'" |
        Where-Object { $_.CommandLine -like '*bot.py*' -or $_.CommandLine -like '*avvia.bat*' } |
        ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
}

function Find-Python {
    foreach ($p in @("$env:ProgramFiles\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Find-Terminal {
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ -and (Test-Path $_) }
    $found = Get-ChildItem -Path $roots -Filter terminal64.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

function Download($url, $dest) {
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

Clear-Host
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host '   INSTALLAZIONE COPIATORE SEGNALI TELEGRAM -> METATRADER 5' -ForegroundColor Cyan
Write-Host '================================================================' -ForegroundColor Cyan

$tmp = Join-Path $env:TEMP 'seers_setup'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

if (-not $Reconfigure) {
    # --- 1. Copia del programma
    Step 1 "Copio il programma in $InstallDir"
    Stop-Bot
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $src = $PSScriptRoot
    if ((Resolve-Path $src).Path.TrimEnd('\') -ne $InstallDir) {
        $keep = @('config.json', 'state.json', 'bot.log', '*.session')
        Get-ChildItem -Path $src -Exclude $keep | Copy-Item -Destination $InstallDir -Recurse -Force
    }
    Get-ChildItem -Path $InstallDir -Recurse | Unblock-File
    Ok 'programma copiato'

    # --- 2. Python
    Step 2 'Python'
    $py = Find-Python
    if (-not $py) {
        Write-Host '    Scarico e installo Python 3.12 (1-2 minuti)...'
        $pyExe = Join-Path $tmp 'python-setup.exe'
        Download $PythonUrl $pyExe
        $p = Start-Process $pyExe -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0' -PassThru
        $p.WaitForExit()
        $py = Find-Python
        if (-not $py) { Fail 'installazione di Python non riuscita' }
    }
    Ok $py

    # --- 3. Librerie
    Step 3 'Librerie Python (telethon, MetaTrader5)'
    $ErrorActionPreference = 'Continue'  # pip scrive avvisi su stderr: non devono fermare lo script
    & $py -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $py -m pip install -r "$InstallDir\requirements.txt" --quiet --disable-pip-version-check
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { Fail 'installazione delle librerie non riuscita (controlla la connessione internet)' }
    Ok 'librerie installate'

    # --- 4. MetaTrader 5
    Step 4 'MetaTrader 5'
    $terminal = Find-Terminal
    if (-not $terminal) {
        Write-Host '    Se il tuo broker ha un suo MetaTrader 5, incolla qui il link per scaricarlo'
        Write-Host '    (dal sito del broker, tasto destro sul pulsante "Scarica MT5" -> Copia link).'
        $url = Read-Host '    Link (oppure premi INVIO per installare MetaTrader 5 standard)'
        if (-not $url) { $url = $Mt5Url }
        Write-Host '    Scarico e installo MetaTrader 5 (2-5 minuti)...'
        $mt5Exe = Join-Path $tmp 'mt5setup.exe'
        Download $url $mt5Exe
        $p = Start-Process $mt5Exe -ArgumentList '/auto' -PassThru
        $p.WaitForExit()
        for ($i = 0; $i -lt 120 -and -not $terminal; $i++) { Start-Sleep 5; $terminal = Find-Terminal }
        if (-not $terminal) { Fail 'installazione di MetaTrader 5 non riuscita' }
        Start-Sleep 10
        Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
    }
    Ok $terminal
} else {
    Stop-Bot
    $py = Find-Python
    $terminal = Find-Terminal
    if (-not $py -or -not $terminal) { Fail 'programma non installato: lancia prima INSTALLA.bat' }
}

# --- 5. Configurazione guidata
Step 5 'Configurazione'
Set-Location $InstallDir
$doWizard = $true
if (-not $Reconfigure -and (Test-Path "$InstallDir\config.json")) {
    $ans = Read-Host '    Esiste gia una configurazione. Vuoi rifarla? (s/N)'
    $doWizard = $ans -match '^[sSyY]'
}
if ($doWizard) {
    & $py "$InstallDir\setup_wizard.py" --terminal $terminal
    if ($LASTEXITCODE -ne 0) { Fail 'configurazione non completata. Rilancia CONFIGURA.bat' }
}

if (-not $Reconfigure) {
    # --- 6. Avvio automatico
    Step 6 'Avvio automatico'
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute "$InstallDir\avvia.bat" -WorkingDirectory $InstallDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
    Ok 'il programma partira da solo ogni volta che Windows si avvia'

    # Server Manager che si apre a ogni accesso: lo disattivo
    Get-ScheduledTask -TaskName ServerManager -ErrorAction SilentlyContinue | Disable-ScheduledTask | Out-Null

    # --- 7. Accesso automatico a Windows dopo un riavvio
    Step 7 'Ripartenza dopo un riavvio della VPS'
    Write-Host '    Dopo un riavvio (es. aggiornamenti di Windows) Windows deve fare l''accesso da solo,'
    Write-Host '    altrimenti MetaTrader e il programma restano spenti finche non ti colleghi.'
    $ans = Read-Host '    Attivo l''accesso automatico? Serve la password di Windows della VPS (S/n)'
    if ($ans -notmatch '^[nN]') {
        Add-Type -AssemblyName System.DirectoryServices.AccountManagement
        $ctx = New-Object System.DirectoryServices.AccountManagement.PrincipalContext('Machine')
        for ($try = 1; $try -le 3; $try++) {
            $sec = Read-Host '    Password di Windows (quella del Desktop remoto)' -AsSecureString
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
            if ($ctx.ValidateCredentials($env:USERNAME, $plain)) { break }
            Warn 'password errata, riprova'
            $plain = $null
        }
        if ($plain) {
            $zip = Join-Path $tmp 'AutoLogon.zip'
            Download $AutologonUrl $zip
            Expand-Archive $zip -DestinationPath "$tmp\autologon" -Force
            & "$tmp\autologon\Autologon64.exe" $env:USERNAME $env:USERDOMAIN $plain /accepteula | Out-Null
            $plain = $null
            Ok 'accesso automatico attivo (password salvata cifrata da Windows)'
        } else {
            Warn 'accesso automatico NON attivato: dopo un riavvio collegati una volta col Desktop remoto'
        }
    }
}

# --- 8. Avvio
Step 8 'Avvio del programma'
Start-ScheduledTask -TaskName $TaskName
Ok 'programma avviato (si apre una finestra nera: NON chiuderla)'

Write-Host "`n================================================================" -ForegroundColor Green
Write-Host '   FATTO! Il copiatore e'' attivo.' -ForegroundColor Green
Write-Host '================================================================' -ForegroundColor Green
Write-Host '  - Ora puoi chiudere il Desktop remoto con la X (NON fare "Disconnetti/Esci").'
Write-Host "  - Il log di tutto quello che succede e' in $InstallDir\bot.log"
Write-Host "  - Per cambiare i dati: doppio clic su $InstallDir\CONFIGURA.bat"
Read-Host "`nPremi INVIO per chiudere questa finestra"
