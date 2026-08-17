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
    $scriptDir = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
    Start-Process powershell.exe -WorkingDirectory "$scriptDir" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
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

Write-Host "[?] Do you want to start the installation now? [Y/n]: " -NoNewline -ForegroundColor Cyan
$confirm = Read-Host
if (-not [string]::IsNullOrWhiteSpace($confirm) -and $confirm -notmatch '^(y|yes|s|si|sí)$') {
    Write-Host "[-] Installation cancelled by user." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit..."
    Exit
}

$InstallDir = "C:\LDAC_Audio"
$SourcePath = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { (Get-Location).Path }
$rebootRequired = $false

# 2. Enable Windows features for WSL2 & Virtual Machine Platform
Write-Host ""
Write-Host "[1/7] Enabling optional Windows features (WSL2 & Virtual Machine Platform)..." -ForegroundColor Cyan
try {
    $dism1 = Start-Process dism.exe -ArgumentList "/online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart" -NoNewWindow -Wait -PassThru
    if ($dism1.ExitCode -eq 3010) { $rebootRequired = $true }

    $dism2 = Start-Process dism.exe -ArgumentList "/online /enable-feature /featurename:VirtualMachinePlatform /all /norestart" -NoNewWindow -Wait -PassThru
    if ($dism2.ExitCode -eq 3010) { $rebootRequired = $true }

    Write-Host "  [+] Virtualization and WSL features enabled successfully." -ForegroundColor Green
} catch {
    Write-Host "  [!] Warning with DISM: $_" -ForegroundColor Yellow
}

# 3. Ensure WSL is installed and updated
Write-Host ""
Write-Host "[2/7] Checking and updating WSL subsystem..." -ForegroundColor Cyan
$wslStatus = & wsl.exe --status 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $wslStatus -match "not installed") {
    Write-Host "  [*] WSL base package not detected. Installing WSL..." -ForegroundColor Yellow
    $wslInstall = Start-Process wsl.exe -ArgumentList "--install --no-distribution" -NoNewWindow -Wait -PassThru
    if ($wslInstall.ExitCode -eq 3010) {
        $rebootRequired = $true
        Write-Host "  [+] WSL package installed (Reboot will be required)." -ForegroundColor Green
    } elseif ($wslInstall.ExitCode -eq 0) {
        Write-Host "  [+] WSL package installed successfully." -ForegroundColor Green
    } else {
        Write-Host "  [*] Attempting WSL engine update..." -ForegroundColor Yellow
        Start-Process wsl.exe -ArgumentList "--update" -NoNewWindow -Wait | Out-Null
    }
} else {
    Write-Host "  [*] Ensuring WSL engine is up to date..." -ForegroundColor Yellow
    Start-Process wsl.exe -ArgumentList "--update" -NoNewWindow -Wait | Out-Null
    Write-Host "  [+] WSL Engine is up to date." -ForegroundColor Green
}

# 4. Install usbipd-win for Bluetooth physical redirection
Write-Host ""
Write-Host "[3/7] Checking usbipd-win installation (USB/IP redirection)..." -ForegroundColor Cyan
$usbipdPath = "C:\Program Files\usbipd-win\usbipd.exe"
$usbipdInPath = Get-Command "usbipd.exe" -ErrorAction SilentlyContinue

if ((-not (Test-Path $usbipdPath)) -and (-not $usbipdInPath)) {
    Write-Host "  [*] usbipd-win not detected. Preparing silent installation..." -ForegroundColor Yellow
    
    $localMsi = Join-Path $SourcePath "usbipd-win_4.3.0.msi"
    if (-not (Test-Path $localMsi)) {
        Write-Host "  [*] Downloading usbipd-win from GitHub official release..." -ForegroundColor Yellow
        $url = "https://github.com/dorssel/usbipd-win/releases/download/v4.3.0/usbipd-win_4.3.0.msi"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
            Invoke-WebRequest -Uri $url -OutFile $localMsi -UseBasicParsing
            Write-Host "    [+] Download completed." -ForegroundColor Green
        } catch {
            Write-Host "    [ERROR] Failed to download usbipd-win: $_" -ForegroundColor Red
            Write-Host "    Please download usbipd-win manually from: $url" -ForegroundColor Yellow
            Write-Host ""
            Read-Host "Press Enter to exit..."
            Exit
        }
    }
    
    # Run silent installation of MSI
    Write-Host "  [*] Running usbipd installer..." -ForegroundColor Yellow
    $installProc = Start-Process msiexec.exe -ArgumentList "/i `"$localMsi`" /qn /norestart" -Wait -PassThru
    if ($installProc.ExitCode -eq 0) {
        Write-Host "  [+] usbipd-win installed successfully." -ForegroundColor Green
    } elseif ($installProc.ExitCode -eq 3010) {
        $rebootRequired = $true
        Write-Host "  [+] usbipd-win installed successfully (Reboot required)." -ForegroundColor Green
    } else {
        Write-Host "  [!] Warning: usbipd installer reported exit code: $($installProc.ExitCode)." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [+] usbipd-win is already present in the system." -ForegroundColor Green
}

# 5. Create Target Directory
Write-Host ""
Write-Host "[4/7] Creating target production directories..." -ForegroundColor Cyan
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
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
    Write-Host "  [ERROR] File 'alpine-rootfs.tar.gz' was not found in: $SourcePath" -ForegroundColor Red
    Write-Host "  Please ensure you extract the entire ZIP file before running install.ps1." -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit..."
    Exit
}

# Shutdown any active instance for safety
& wsl.exe --shutdown 2>$null | Out-Null
$wslList = (& wsl.exe -l -q 2>$null | Out-String) -replace "`0", ""
if ($wslList -match "Alpine") {
    Write-Host "  [*] Previous Alpine distribution detected. Registering clean instance..." -ForegroundColor Yellow
    & wsl.exe --unregister Alpine 2>$null | Out-Null
    Start-Sleep -Seconds 1
}

# Import distribution
Write-Host "  [*] Importing Alpine rootfs into WSL2..." -ForegroundColor Yellow
$importOutput = & wsl.exe --import Alpine "$wslDir" "$tarFile" --version 2 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [+] Alpine VM imported successfully." -ForegroundColor Green
} else {
    Write-Host "  [ERROR] Failed to import VM into WSL (Exit code $LASTEXITCODE)." -ForegroundColor Red
    if (-not [string]::IsNullOrWhiteSpace($importOutput)) {
        Write-Host "  WSL Message: $importOutput" -ForegroundColor Red
    }
    if ($rebootRequired) {
        Write-Host ""
        Write-Host "  [!] Virtualization features require a Windows reboot before WSL can import VMs." -ForegroundColor Yellow
        Write-Host "      Please restart your computer and execute install.ps1 again." -ForegroundColor Yellow
    }
    Write-Host ""
    Read-Host "Press Enter to exit..."
    Exit
}

# 7. Configure Custom Kernel and optimal RAM Limit (320 MB)
Write-Host ""
Write-Host "[6/7] Configuring custom WSL audio Kernel and RAM limit..." -ForegroundColor Cyan
$bzImageSource = Join-Path $SourcePath "bzImage"
$bzImageDest = Join-Path $kernelDir "bzImage"

$hasCustomKernel = $false
if (Test-Path $bzImageSource) {
    Copy-Item $bzImageSource $bzImageDest -Force | Out-Null
    Write-Host "  [+] Custom Kernel (bzImage) copied to $bzImageDest." -ForegroundColor Green
    $hasCustomKernel = $true
} else {
    Write-Host "  [!] Warning: 'bzImage' was not found in the local folder. The default Windows kernel will be used." -ForegroundColor Yellow
}

# Write global user .wslconfig
$wslconfigPath = Join-Path $env:USERPROFILE ".wslconfig"
if ($hasCustomKernel) {
    $wslconfigLines = @(
        "[wsl2]",
        "kernel=C:\\LDAC_Audio\\kernel\\bzImage",
        "memory=320MB",
        "processors=4",
        "guiApplications=false"
    )
} else {
    $wslconfigLines = @(
        "[wsl2]",
        "memory=320MB",
        "processors=4",
        "guiApplications=false"
    )
}

try {
    [System.IO.File]::WriteAllLines($wslconfigPath, $wslconfigLines, [System.Text.Encoding]::UTF8)
    Write-Host "  [+] .wslconfig successfully set to optimal 320 MB RAM limit." -ForegroundColor Green
} catch {
    Write-Host "  [!] Failed to write to ${wslconfigPath}: $_" -ForegroundColor Red
}

# Shutdown WSL to force load new settings
& wsl.exe --shutdown 2>$null | Out-Null

# 8. Copy Windows support files
Write-Host ""
Write-Host "[7/7] Copying control scripts and Windows frontend..." -ForegroundColor Cyan
$filesToCopy = @(
    "LDAC_Audio.exe",
    "ldac_paths.json",
    "ldac_tray.py",
    "emisor_audio.py",
    "receptor_audio.sh",
    "prepare_alpine.py",
    "prepare_scream.py",
    "ldac_config.json",
    "LDAC_LDAC_Audio.bat"
)

$copiedCount = 0
foreach ($file in $filesToCopy) {
    $src = Join-Path $SourcePath $file
    $dst = Join-Path $InstallDir $file
    if (Test-Path $src) {
        Copy-Item $src $dst -Force | Out-Null
        $copiedCount++
    }
}
Write-Host "  [+] $copiedCount control files copied to $InstallDir." -ForegroundColor Green

# 9. Create elegant shortcuts on the Desktop
try {
    Write-Host "  [*] Creating Desktop shortcuts..." -ForegroundColor Yellow
    $WshShell = New-Object -ComObject WScript.Shell
    $desktopDir = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopDir "LDAC Audio.lnk"
    $ShortcutProd = $WshShell.CreateShortcut($shortcutPath)
    
    $exePath = Join-Path $InstallDir "LDAC_Audio.exe"
    if (Test-Path $exePath) {
        $ShortcutProd.TargetPath = $exePath
        $ShortcutProd.IconLocation = "$exePath,0"
    } else {
        $ShortcutProd.TargetPath = Join-Path $InstallDir "LDAC_LDAC_Audio.bat"
        $ShortcutProd.IconLocation = "shell32.dll,224"
    }
    
    $ShortcutProd.WorkingDirectory = $InstallDir
    $ShortcutProd.Description = "Start wireless LDAC Audio transmission"
    $ShortcutProd.Save()
    
    Write-Host "  [+] Desktop shortcut created successfully." -ForegroundColor Green
} catch {
    Write-Host "  [!] Failed to create Desktop shortcuts automatically: $_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "                INSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " All components have been configured:" -ForegroundColor Gray
Write-Host " - Alpine Linux VM imported under WSL2" -ForegroundColor Gray
Write-Host " - Optimal 320 MB RAM limit configured in .wslconfig" -ForegroundColor Gray
Write-Host " - usbipd-win installed for Bluetooth management" -ForegroundColor Gray
Write-Host " - Desktop shortcut created ('LDAC Audio')" -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host ""
if ($rebootRequired) {
    Write-Host "[!] IMPORTANT: Virtualization features were newly enabled." -ForegroundColor Yellow
    Write-Host "    Please restart Windows to complete the setup." -ForegroundColor Yellow
} else {
    Write-Host "[*] Setup is complete. You can start LDAC Audio from your Desktop." -ForegroundColor Green
}
Write-Host ""

Read-Host "Press Enter to exit..."
