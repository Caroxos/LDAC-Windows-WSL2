import os
import re
import time
import subprocess
from logger import log_message, run_logged, popen_logged, WSL_DISTRO, WSL_USER
from sys_helpers import (
    CREATE_NO_WINDOW,
    _startupinfo,
    resolve_usbipd_path,
    show_native_message_box
)

USBIPD = resolve_usbipd_path()

def ensure_usbipd_service():
    """Garantiza que el servicio 'usbipd' de Windows esté iniciado."""
    try:
        res = run_logged(
            ["sc.exe", "query", "usbipd"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
        )
        stdout_str = res.stdout.decode("utf-8", errors="replace")
        if "STOPPED" in stdout_str or "1  STOPPED" in stdout_str:
            run_logged(
                ["sc.exe", "start", "usbipd"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10
            )
            time.sleep(1.5)
    except Exception as e:
        log_message(f"ensure_usbipd_service error: {str(e)}")

def get_dynamic_busid(ctx):
    """Busca dinámicamente el BUSID de un dispositivo compatible con Bluetooth."""
    try:
        res = run_logged(
            [USBIPD, "list"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
        )
        stdout_str = res.stdout.decode("utf-8", errors="replace")
        for line in stdout_str.splitlines():
            if any(w in line.lower() for w in ["bluetooth", "wireless bluetooth", "generic bluetooth"]):
                tokens = line.strip().split()
                if tokens:
                    detected_busid = tokens[0]
                    if re.match(r"^\d+-\d+(?:\.\d+)*$", detected_busid):
                        ctx.BUSID = detected_busid
                        log_message(f"Detected Bluetooth adapter at BUSID {ctx.BUSID}")
                        return ctx.BUSID
    except Exception as e:
        log_message(f"get_dynamic_busid error: {str(e)}")
    return ctx.BUSID

def ensure_device_bound(ctx):
    """Verifica si el dispositivo está compartido y si no, lo comparte solicitando UAC."""
    get_dynamic_busid(ctx)
    try:
        res = run_logged(
            [USBIPD, "list"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
        )
        is_shared = False
        stdout_str = res.stdout.decode("utf-8", errors="replace")
        for line in stdout_str.splitlines():
            if ctx.BUSID in line:
                if "Shared" in line or "Attached" in line:
                    is_shared = True
                    break
        if not is_shared:
            log_message(f"Device at {ctx.BUSID} not shared, launching elevated bind powershell...")
            run_logged([
                "powershell.exe", "-Command",
                f"Start-Process '{USBIPD}' -ArgumentList 'bind --busid {ctx.BUSID}' -Verb RunAs -WindowStyle Hidden"
            ], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
            time.sleep(2)
    except Exception as e:
        log_message(f"ensure_device_bound error: {str(e)}")

def ensure_bluetooth_active(ctx, progress_callback=None):
    """Garantiza que el adaptador Bluetooth esté acoplado en WSL y bluetoothd esté corriendo."""
    get_dynamic_busid(ctx)
    def log(msg):
        log_message(msg)
        if progress_callback:
            progress_callback(msg)

    # Validar que usbipd-win esté instalado
    if not os.path.exists(USBIPD) and not shutil.which("usbipd"):
        show_native_message_box(
            "usbipd-win Required",
            "The 'usbipd-win' tool was not found on your system.\n\n"
            "Please download and install it from the official repository:\n"
            "https://github.com/duncanthrax/scream/releases (usbipd-win)\n"
            "to share your physical Bluetooth adapter with WSL2."
        )
        return False

    ensure_usbipd_service()

    # Comando de arranque con verificación de Ping Probe y hciconfig retry loop
    startup_cmd = (
        "mkdir -p /var/run/dbus /run/dbus && "
        "dbus-send --system --print-reply --reply-timeout=2000 --dest=org.freedesktop.DBus / org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1 || (rm -f /run/dbus/dbus.pid /var/run/dbus/pid /var/run/dbus/system_bus_socket 2>/dev/null; dbus-daemon --system --fork; killall -9 bluetoothd 2>/dev/null); "
        "pgrep bluetoothd >/dev/null || setsid /usr/lib/bluetooth/bluetoothd & "
        "sleep 2; "
        "for i in 1 2 3; do hciconfig hci0 up 2>/dev/null && break; sleep 1; done; "
        "for i in 1 2 3 4 5; do bluetoothctl show 2>/dev/null | grep -q 'Powered: yes' && break; bluetoothctl power on 2>/dev/null; sleep 1; done; "
        "bluetoothctl pairable on 2>/dev/null; "
        "export XDG_RUNTIME_DIR=/tmp/runtime-root && "
        "export PULSE_SERVER=unix:/tmp/runtime-root/pulse/native && "
        "mkdir -p /tmp/runtime-root && chmod 700 /tmp/runtime-root && "
        "pgrep pipewire >/dev/null || setsid env XDG_RUNTIME_DIR=/tmp/runtime-root PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pipewire >/dev/null 2>&1 & "
        "pgrep pipewire-pulse >/dev/null || (rm -f /tmp/runtime-root/pulse/native 2>/dev/null; setsid env XDG_RUNTIME_DIR=/tmp/runtime-root PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pipewire-pulse >/dev/null 2>&1 &); "
        "killall -9 wireplumber 2>/dev/null; setsid env XDG_RUNTIME_DIR=/tmp/runtime-root PULSE_SERVER=unix:/tmp/runtime-root/pulse/native wireplumber >/dev/null 2>&1 & "
        "sleep 0.5"
    )

    # 1. Comprobar si hci0 ya existe Y es funcional
    log("Checking Bluetooth adapter (hci0)...")
    try:
        res = run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "test", "-d", "/sys/class/bluetooth/hci0"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=30
        )
    except Exception as e:
        log(f"Error checking adapter: {str(e)}")
        return False

    if res.returncode == 0:
        # Comprobar si D-Bus y bluetoothd ya están activos y respondiendo
        dbus_ok = False
        try:
            dbus_check = run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "dbus-send", "--system", "--print-reply", "--reply-timeout=1500", "--dest=org.bluez", "/", "org.freedesktop.DBus.Peer.Ping"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
            )
            if dbus_check.returncode == 0:
                dbus_ok = True
        except Exception:
            pass
        
        if dbus_ok:
            log("hci0 adapter active and Bluetooth services already running. Skipping startup_cmd.")
            return True
            
        log("hci0 adapter active but Bluetooth services not responding. Starting services...")
        try:
            run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "ash", "-c", startup_cmd],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20
            )
        except Exception:
            pass
        return True

    # 2. Si no, hacer attach
    log("Binding Bluetooth adapter via USBIPD...")
    ensure_device_bound(ctx)

    log("Pre-loading kernel drivers in Alpine...")
    try:
        run_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "modprobe", "vhci-hcd"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
    except Exception:
        pass
    try:
        run_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "modprobe", "btusb"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
    except Exception:
        pass
    time.sleep(1)

    # Mantener viva la VM durante todo el attach
    boot_proc = popen_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sleep", "30"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo())
    time.sleep(1)

    log("Attaching Bluetooth adapter to WSL2...")
    try:
        run_logged([USBIPD, "attach", "--wsl", WSL_DISTRO, "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20)
    except Exception:
        log("Attach timed out, checking if hci0 appeared anyway...")

    # Esperar hci0 (max 15s)
    hci0_found = False
    for i in range(15):
        log(f"Waiting for Bluetooth adapter... ({i+1}/15s)")
        try:
            res = run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "test", "-d", "/sys/class/bluetooth/hci0"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
            )
            if res.returncode == 0:
                hci0_found = True
                break
        except Exception:
            pass
        time.sleep(1)

    try:
        boot_proc.terminate()
    except Exception:
        pass

    if not hci0_found:
        log("Error: Bluetooth adapter (hci0) not detected. Check your USB dongle.")
        return False

    log("Starting D-Bus and bluetoothd in Alpine...")
    try:
        run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "ash", "-c", startup_cmd],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20
        )
    except Exception:
        pass
    log("Bluetooth ready for scanning/connection.")
    return True
