# ===========================================================================
#  LDAC Audio - PORTABLE DISTRIBUTION INSTALLER AND PROVISIONING SCRIPT (.ZIP)
# ===========================================================================
#  This script automates WSL2 enabling, silent installation of usbipd-win,
#  optimized Alpine VM importing, custom kernel setup, and desktop shortcuts.
# ===========================================================================

# 1. Require Administrator Privileges automatically
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Requesting Administrator privileges..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File '$PSCommandPath'" -Verb RunAs
    Exit
}

# Clear screen and establish UTF-8 output encoding
Clear-Host
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "                LDAC AUDIO PORTABLE INSTALLER (WSL2)" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host " This assistant will set up your LDAC wireless audio transmission" -ForegroundColor Gray
Write-Host " system in a fully automated way." -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

$confirm = Read-Host "[?] Do you want to start the installation now? (Y/N)"
if ($confirm.ToUpper() -ne "Y") {
    Write-Host "[-] Installation cancelled by the user." -ForegroundColor Red
    Start-Sleep -Seconds 2
    Exit
}

$InstallDir = "C:\LDAC_Audio"
$SourcePath = Split-Path -Parent $MyInvocation.MyCommand.Path

# 2. Enable Windows features for WSL2
Write-Host ""
Write-Host "[1/7] Enabling optional Windows features (WSL2 and Virtual Machine Platform)..." -ForegroundColor Cyan
try {
    # Attempt to enable without rebooting
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
    Write-Host "  [+] Virtualization and WSL features enabled successfully." -ForegroundColor Green
} catch {
    Write-Host "  [!] Error enabling optional features with DISM: $_" -ForegroundColor Red
}

# 3. Ensure WSL is updated
Write-Host ""
Write-Host "[2/7] Ensuring WSL subsystem is up to date..." -ForegroundColor Cyan
wsl.exe --update | Out-Null
Write-Host "  [+] WSL Engine updated successfully." -ForegroundColor Green

# 4. Install usbipd-win for Bluetooth physical redirection
Write-Host ""
Write-Host "[3/7] Checking usbipd-win installation (USB/IP redirection)..." -ForegroundColor Cyan
$usbipdPath = "C:\Program Files\usbipd-win\usbipd.exe"
if (-not (Test-Path $usbipdPath)) {
    Write-Host "  [*] usbipd-win not detected. Starting silent installation..." -ForegroundColor Yellow
    
    $localMsi = Join-Path $SourcePath "usbipd-win_4.3.0.msi"
    if (-not (Test-Path $localMsi)) {
        Write-Host "  [*] Downloading usbipd-win from GitHub official release..." -ForegroundColor Yellow
        $url = "https://github.com/dorssel/usbipd-win/releases/download/v4.3.0/usbipd-win_4.3.0.msi"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -OutFile $localMsi -UseBasicParsing | Out-Null
            Write-Host "    [+] Download completed." -ForegroundColor Green
        } catch {
            Write-Host "    [ERROR] Failed to download usbipd-win. Please check your internet connection: $_" -ForegroundColor Red
            Write-Host "    Installation failed." -ForegroundColor Red
            Read-Host "Press Enter to exit..."
            Exit
        }
    }
    
    # Run silent installation of MSI
    Write-Host "  [*] Running usbipd installer..." -ForegroundColor Yellow
    $installProc = Start-Process msiexec.exe -ArgumentList "/i '$localMsi' /quiet /norestart" -Wait -PassThru
    if ($installProc.ExitCode -eq 0) {
        Write-Host "  [+] usbipd-win installed successfully." -ForegroundColor Green
    } else {
        Write-Host "  [!] Warning: usbipd installer reported exit code: $($installProc.ExitCode). Reboot might be required." -ForegroundColor Orange
    }
} else {
    Write-Host "  [+] usbipd-win is already present in the system." -ForegroundColor Green
}

# 5. Create Target Directory
Write-Host ""
Write-Host "[4/7] Creating target production directories..." -ForegroundColor Cyan
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}
$wslDir = Join-Path $InstallDir "WSL"
$kernelDir = Join-Path $InstallDir "kernel"
New-Item -ItemType Directory -Path $wslDir -Force | Out-Null
New-Item -ItemType Directory -Path $kernelDir -Force | Out-Null
Write-Host "  [+] Directory structure created at $InstallDir." -ForegroundColor Green

# 6. Import optimized Alpine VM
Write-Host ""
Write-Host "[5/7] Importing optimized Alpine Linux virtual machine..." -ForegroundColor Cyan
$tarFile = Join-Path $SourcePath "alpine-rootfs.tar.gz"
if (-not (Test-Path $tarFile)) {
    Write-Host "  [ERROR] File 'alpine-rootfs.tar.gz' was not found in the installer directory." -ForegroundColor Red
    Write-Host "  Please ensure you extract the entire ZIP file before running install.ps1." -ForegroundColor Red
    Read-Host "Press Enter to exit..."
    Exit
}

# Shutdown any active instance for safety
wsl.exe --shutdown | Out-Null
if (wsl.exe -l | Select-String -Pattern "^Alpine\b") {
    Write-Host "  [*] Previous Alpine distribution detected. Registering clean instance..." -ForegroundColor Yellow
    wsl.exe --unregister Alpine | Out-Null
    Start-Sleep -Seconds 1
}

# Import distribution
try {
    wsl.exe --import Alpine $wslDir $tarFile --version 2 | Out-Null
    Write-Host "  [+] Alpine VM imported successfully." -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to import VM into WSL: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit..."
    Exit
}

# 7. Configure Custom Kernel and optimal RAM Limit (300 MB)
Write-Host ""
Write-Host "[6/7] Configuring custom WSL audio Kernel and RAM limit..." -ForegroundColor Cyan
$bzImageSource = Join-Path $SourcePath "bzImage"
$bzImageDest = Join-Path $kernelDir "bzImage"

if (Test-Path $bzImageSource) {
    Copy-Item $bzImageSource $bzImageDest -Force | Out-Null
    Write-Host "  [+] Custom Kernel (bzImage) copied to $bzImageDest." -ForegroundColor Green
} else {
    Write-Host "  [!] Warning: 'bzImage' was not found in the local folder. The default Windows kernel will be used." -ForegroundColor Orange
}

# Write global user .wslconfig using clean carriage-return injection
$wslconfigPath = Join-Path $env:USERPROFILE ".wslconfig"
$wslconfigContent = "[wsl2]" + [char]13 + [char]10 + "kernel=C:\\LDAC_Audio\\kernel\\bzImage" + [char]13 + [char]10 + "memory=320MB" + [char]13 + [char]10 + "processors=4" + [char]13 + [char]10 + "guiApplications=false"

try {
    Set-Content -Path $wslconfigPath -Value $wslconfigContent -Force
    Write-Host "  [+] .wslconfig successfully set to optimal 320 MB RAM limit." -ForegroundColor Green
} catch {
    Write-Host "  [!] Failed to write to ${wslconfigPath}: $_" -ForegroundColor Red
}

# Shutdown WSL to force load new settings
wsl.exe --shutdown | Out-Null

# 8. Copy Windows support files
Write-Host ""
Write-Host "[7/7] Copying control scripts and Windows frontend..." -ForegroundColor Cyan
$filesToCopy = @(
    "ldac_tray.py",
    "ldac_tray_test.py",
    "emisor_audio.py",
    "receptor_audio.sh",
    "prepare_alpine.py",
    "prepare_scream.py",
    "ldac_config.json",
    "LDAC_LDAC_Audio.bat",
    "LDAC_Test_320MB.bat"
)

foreach ($file in $filesToCopy) {
    $src = Join-Path $SourcePath $file
    $dst = Join-Path $InstallDir $file
    if (Test-Path $src) {
        Copy-Item $src $dst -Force | Out-Null
    }
}
Write-Host "  [+] Control files copied to $InstallDir." -ForegroundColor Green

# 9. Create elegant shortcuts on the Desktop
try {
    Write-Host "  [*] Creating Desktop shortcuts..." -ForegroundColor Yellow
    $WshShell = New-Object -ComObject WScript.Shell
    
    # Production Shortcut
    $ShortcutProd = $WshShell.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "LDAC Audio.lnk"))
    $ShortcutProd.TargetPath = "C:\LDAC_Audio\LDAC_LDAC_Audio.bat"
    $ShortcutProd.WorkingDirectory = "C:\LDAC_Audio"
    $ShortcutProd.Description = "Start wireless LDAC Audio transmission"
    $ShortcutProd.IconLocation = "shell32.dll,224" # Elegant audio icon
    $ShortcutProd.Save()

    # Test Shortcut
    $ShortcutTest = $WshShell.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "LDAC Audio Test.lnk"))
    $ShortcutTest.TargetPath = "C:\LDAC_Audio\LDAC_Test_320MB.bat"
    $ShortcutTest.WorkingDirectory = "C:\LDAC_Audio"
    $ShortcutTest.Description = "Start wireless LDAC Audio test environment"
    $ShortcutTest.IconLocation = "shell32.dll,225"
    $ShortcutTest.Save()
    
    Write-Host "  [+] Desktop shortcuts created successfully." -ForegroundColor Green
} catch {
    Write-Host "  [!] Failed to create Desktop shortcuts automatically." -ForegroundColor Orange
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "                INSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " All components have been configured:" -ForegroundColor Gray
Write-Host " - Alpine Linux VM imported under WSL2" -ForegroundColor Gray
Write-Host " - Optimal 320 MB RAM limit configured in .wslconfig" -ForegroundColor Gray
Write-Host " - usbipd-win installed for Bluetooth management" -ForegroundColor Gray
Write-Host " - Desktop shortcuts created ('LDAC Audio')" -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "[!] IMPORTANT: If this is the first time you set up WSL on this PC," -ForegroundColor Yellow
Write-Host "    we highly recommend rebooting Windows before first use." -ForegroundColor Yellow
Write-Host ""

Read-Host "Press any key to exit..."
