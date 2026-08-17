# ===========================================================================
#  LDAC Audio - UNINSTALLER AND CLEANUP SCRIPT
# ===========================================================================
#  This script automates unregistering the Alpine WSL2 VM, deleting
#  desktop shortcuts, and removing production files from C:\LDAC_Audio.
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
Write-Host "                LDAC AUDIO UNINSTALLER" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host " This script will remove LDAC Audio WSL2 components," -ForegroundColor Gray
Write-Host " desktop shortcuts, and production files." -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[?] Are you sure you want to uninstall LDAC Audio? [y/N]: " -NoNewline -ForegroundColor Yellow
$confirm = Read-Host
if ($confirm -notmatch '^(y|yes|s|si|sí)$') {
    Write-Host "[-] Uninstallation cancelled by user." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit..."
    Exit
}

$InstallDir = "C:\LDAC_Audio"

# 2. Stop running processes
Write-Host ""
Write-Host "[1/5] Stopping active LDAC Audio processes..." -ForegroundColor Cyan
try {
    Get-Process -Name "LDAC_Audio" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "  [+] Active processes stopped." -ForegroundColor Green
} catch {
    Write-Host "  [*] No active LDAC Audio processes found." -ForegroundColor Gray
}

# 3. Unregister Alpine WSL2 instance
Write-Host ""
Write-Host "[2/5] Unregistering Alpine WSL2 distribution..." -ForegroundColor Cyan
try {
    & wsl.exe --shutdown 2>$null | Out-Null
    $wslList = (& wsl.exe -l -q 2>$null | Out-String) -replace "`0", ""
    if ($wslList -match "Alpine") {
        & wsl.exe --unregister Alpine 2>$null | Out-Null
        Write-Host "  [+] Alpine WSL2 instance unregistered successfully." -ForegroundColor Green
    } else {
        Write-Host "  [*] No Alpine WSL2 instance was found." -ForegroundColor Gray
    }
} catch {
    Write-Host "  [!] Warning while unregistering WSL distribution: $_" -ForegroundColor Yellow
}

# 4. Clean and restore .wslconfig if pointing to LDAC custom kernel
Write-Host ""
Write-Host "[3/5] Cleaning custom WSL kernel configuration (.wslconfig)..." -ForegroundColor Cyan
$wslconfigPath = Join-Path $env:USERPROFILE ".wslconfig"
if (Test-Path $wslconfigPath) {
    try {
        $lines = Get-Content $wslconfigPath
        $newLines = @()
        foreach ($line in $lines) {
            if ($line -match "kernel=.*LDAC_Audio.*bzImage") {
                continue
            }
            $newLines += $line
        }
        
        $effectiveLines = $newLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notmatch '^\[wsl2\]$' }
        if ($effectiveLines.Count -eq 0) {
            Remove-Item $wslconfigPath -Force -ErrorAction SilentlyContinue
            Write-Host "  [+] Cleaned .wslconfig (reverted to default Windows WSL settings)." -ForegroundColor Green
        } else {
            [System.IO.File]::WriteAllLines($wslconfigPath, $newLines, [System.Text.Encoding]::UTF8)
            Write-Host "  [+] Removed LDAC custom kernel entry from .wslconfig." -ForegroundColor Green
        }
        & wsl.exe --shutdown 2>$null | Out-Null
    } catch {
        Write-Host "  [!] Warning updating .wslconfig: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [*] No .wslconfig file present." -ForegroundColor Gray
}

# 5. Remove Desktop Shortcut
Write-Host ""
Write-Host "[4/5] Removing Desktop shortcuts..." -ForegroundColor Cyan
$desktopShortcut = [System.IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "LDAC Audio.lnk")
if (Test-Path $desktopShortcut) {
    try {
        Remove-Item -Path $desktopShortcut -Force
        Write-Host "  [+] Desktop shortcut removed." -ForegroundColor Green
    } catch {
        Write-Host "  [!] Could not remove Desktop shortcut: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [*] Desktop shortcut not found." -ForegroundColor Gray
}

# 6. Clean production directory C:\LDAC_Audio
Write-Host ""
Write-Host "[5/5] Cleaning production directory ($InstallDir)..." -ForegroundColor Cyan
if (Test-Path $InstallDir) {
    try {
        Remove-Item -Path $InstallDir -Recurse -Force
        Write-Host "  [+] Directory $InstallDir removed successfully." -ForegroundColor Green
    } catch {
        Write-Host "  [!] Could not fully remove ${InstallDir}: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [*] Directory $InstallDir does not exist." -ForegroundColor Gray
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "                UNINSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host ""

Read-Host "Press Enter to exit..."
