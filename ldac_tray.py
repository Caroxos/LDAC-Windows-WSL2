import sys
import os
import ctypes
import subprocess
import threading
import time

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Elevacion UAC: no requerida si el dispositivo ya esta compartido (bound)
# ---------------------------------------------------------------------------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

# Ejecutar como usuario estandar para mantener la sesion de WSL y evitar bloqueos de disco (.vhdx)


# ---------------------------------------------------------------------------
# Imports que requieren que ya seamos admin / que pystray este instalado
# ---------------------------------------------------------------------------
import pystray
from PIL import Image, ImageDraw, ImageFont
import audioop
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import pyaudiowpatch as pyaudio
import socket
import re
import json
import tempfile
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

# ---------------------------------------------------------------------------
# Configuracion global
# ---------------------------------------------------------------------------
BUSID        = "1-12"
INSTALL_DIR  = os.path.dirname(os.path.abspath(__file__))
EMISOR_PY    = os.path.join(INSTALL_DIR, "emisor_audio.py")
UBSIPD       = r"C:\Program Files\usbipd-win\usbipd.exe"
USBIPD       = r"C:\Program Files\usbipd-win\usbipd.exe"
UDP_PORT     = 5005
CHUNK        = 1024
STATS_FILE   = os.path.join(tempfile.gettempdir(), "ldac_stats.json")

# ---------------------------------------------------------------------------
# Gestión de configuración de auriculares
# ---------------------------------------------------------------------------
def load_config():
    CONFIG_FILE = os.path.join(INSTALL_DIR, "ldac_config.json")
    default_config = {
        "selected_mac": "01:02:03:04:1E:19",
        "selected_name": "Wireless Headphones",
        "ldac_mode": "hq"
    }
    if not os.path.exists(CONFIG_FILE):
        return default_config
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
            if "ldac_mode" not in cfg:
                cfg["ldac_mode"] = "hq"
            return cfg
    except Exception:
        return default_config

def save_config(mac, name, ldac_mode=None):
    CONFIG_FILE = os.path.join(INSTALL_DIR, "ldac_config.json")
    try:
        current = load_config()
        mode = ldac_mode if ldac_mode is not None else current.get("ldac_mode", "hq")
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "selected_mac": mac,
                "selected_name": name,
                "ldac_mode": mode
            }, f, indent=2)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Prevención de Instancias Duplicadas
# ---------------------------------------------------------------------------
def is_pid_running(pid):
    """Verifica de forma nativa en Windows si un PID está corriendo y activo."""
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259 # STILL_ACTIVE es 259
        return False
    except Exception:
        return False

def kill_pid(pid):
    """Termina de forma forzada un proceso por su PID."""
    try:
        os.kill(pid, 9)
        time.sleep(0.5)
    except Exception:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], creationflags=0x08000000, startupinfo=_startupinfo(), timeout=3)
        except Exception:
            pass

def check_single_instance():
    """Garantiza que solo haya una instancia abierta de este script, consultando al usuario si desea cerrar la anterior."""
    import tempfile
    script_name = os.path.basename(sys.argv[0]).replace(".py", "")
    pid_file = os.path.join(tempfile.gettempdir(), f"ldac_audio_{script_name}.pid")
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                old_pid = int(f.read().strip())
            
            if old_pid != os.getpid() and is_pid_running(old_pid):
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                
                resp = messagebox.askyesno(
                    "Duplicate Instance Detected",
                    f"Another instance of LDAC Audio is active (PID {old_pid}) which may interfere with Bluetooth connection.\n\n"
                    "Do you want to automatically close the previous instance and launch this new one?",
                    parent=root
                )
                root.destroy()
                
                if resp:
                    kill_pid(old_pid)
                else:
                    sys.exit(0)
        except Exception:
            pass
            
    try:
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

def cleanup_pid_file():
    """Elimina el archivo PID de la instancia actual al salir."""
    try:
        import tempfile
        script_name = os.path.basename(sys.argv[0]).replace(".py", "")
        pid_file = os.path.join(tempfile.gettempdir(), f"ldac_audio_{script_name}.pid")
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Helpers para el subsistema Bluetooth de WSL
# ---------------------------------------------------------------------------
def ensure_usbipd_service():
    """Garantiza que el servicio 'usbipd' de Windows esté iniciado."""
    try:
        res = subprocess.run(
            ["sc.exe", "query", "usbipd"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
        )
        if "STOPPED" in res.stdout or "1  STOPPED" in res.stdout:
            subprocess.run(
                ["sc.exe", "start", "usbipd"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
            )
            time.sleep(1.5)
    except Exception:
        pass

def get_dynamic_busid():
    """Busca dinámicamente el BUSID de un dispositivo compatible con Bluetooth en usbipd list."""
    global BUSID
    try:
        res = subprocess.run(
            [USBIPD, "list"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
        )
        for line in res.stdout.splitlines():
            if any(w in line.lower() for w in ["bluetooth", "wireless bluetooth", "generic bluetooth"]):
                tokens = line.strip().split()
                if tokens:
                    detected_busid = tokens[0]
                    if re.match(r"^\d+-\d+(?:\.\d+)*$", detected_busid):
                        BUSID = detected_busid
                        return BUSID
    except Exception:
        pass
    return BUSID

def ensure_device_bound():
    """Verifica si el dispositivo está compartido (Shared/Attached) y si no, lo comparte solicitando UAC."""
    get_dynamic_busid()
    try:
        res = subprocess.run(
            [USBIPD, "list"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
        )
        is_shared = False
        for line in res.stdout.splitlines():
            if BUSID in line:
                if "Shared" in line or "Attached" in line:
                    is_shared = True
                    break
        if not is_shared:
            # Solicitar elevación solo para el comando bind de usbipd
            subprocess.run([
                "powershell.exe", "-Command",
                f"Start-Process '{USBIPD}' -ArgumentList 'bind --busid {BUSID}' -Verb RunAs -WindowStyle Hidden"
            ], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
            time.sleep(2) # Dar tiempo a que el usuario acepte el prompt
    except Exception:
        pass

def ensure_bluetooth_active(progress_callback=None):
    """Garantiza que el adaptador Bluetooth esté acoplado en WSL y bluetoothd esté corriendo."""
    get_dynamic_busid()
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    # Asegurar que el servicio de Windows esté iniciado
    ensure_usbipd_service()

    # Comando robusto de arranque para D-Bus, bluetoothd, PipeWire y WirePlumber
    # NOTA: bluetoothctl power on usa timeout 3 para no bloquearse si bluetoothd aun no responde
    startup_cmd = (
        "mkdir -p /run/dbus && "
        "pgrep dbus-daemon >/dev/null || (rm -f /run/dbus/dbus.pid /var/run/dbus/pid 2>/dev/null; dbus-daemon --system --fork); "
        "pgrep bluetoothd >/dev/null || setsid /usr/lib/bluetooth/bluetoothd & "
        "sleep 1; "
        "timeout 3 bluetoothctl power on 2>/dev/null; timeout 3 bluetoothctl pairable on 2>/dev/null; "
        "export XDG_RUNTIME_DIR=/tmp/runtime-root && "
        "export PULSE_SERVER=unix:/tmp/runtime-root/pulse/native && "
        "mkdir -p /tmp/runtime-root && chmod 700 /tmp/runtime-root && "
        "pgrep pipewire >/dev/null || setsid env XDG_RUNTIME_DIR=/tmp/runtime-root PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pipewire >/dev/null 2>&1 & "
        "pgrep pipewire-pulse >/dev/null || setsid env XDG_RUNTIME_DIR=/tmp/runtime-root PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pipewire-pulse >/dev/null 2>&1 & "
        "pgrep wireplumber >/dev/null || setsid env XDG_RUNTIME_DIR=/tmp/runtime-root PULSE_SERVER=unix:/tmp/runtime-root/pulse/native wireplumber >/dev/null 2>&1 & "
        "sleep 0.5"
    )

    # 1. Comprobar si hci0 ya existe Y es funcional
    # 1. Comprobar si hci0 ya existe Y es funcional
    log("Checking Bluetooth adapter (hci0)...")
    try:
        res = subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "test", "-d", "/sys/class/bluetooth/hci0"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=30
        )
    except (subprocess.TimeoutExpired, Exception) as e:
        log(f"Error checking adapter: {str(e)}")
        return False

    if res.returncode == 0:
        # Verificar que el adaptador realmente responde (no es un hci0 fantasma de sesion anterior)
        chk = subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "cat", "/sys/class/bluetooth/hci0/type"],
            capture_output=True, creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
        )
        if chk.returncode == 0:
            log("hci0 adapter active. Starting services...")
            try:
                subprocess.run(
                    ["wsl", "-d", "Alpine", "-u", "root", "ash", "-c", startup_cmd],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20
                )
            except subprocess.TimeoutExpired:
                pass
            return True
        else:
            log("hci0 adapter not responding, retrying attach...")

    # 2. Si no, hacer attach
    log("Binding Bluetooth adapter via USBIPD...")
    ensure_device_bound()

    log("Pre-loading kernel drivers in Alpine...")
    try:
        subprocess.run(["wsl", "-d", "Alpine", "-u", "root", "modprobe", "vhci-hcd"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
    except subprocess.TimeoutExpired:
        pass
    try:
        subprocess.run(["wsl", "-d", "Alpine", "-u", "root", "modprobe", "btusb"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(1)

    # Mantener viva la VM durante todo el attach + espera de hci0 (30s de margen)
    boot_proc = subprocess.Popen(["wsl", "-d", "Alpine", "-u", "root", "sleep", "30"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo())
    time.sleep(1)

    log("Attaching Bluetooth adapter to WSL2...")
    try:
        subprocess.run([USBIPD, "attach", "--wsl", "Alpine", "--busid", BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20)
    except subprocess.TimeoutExpired:
        log("Attach timed out, checking if hci0 appeared anyway...")

    # Esperar hci0 (max 15s) — boot_proc sigue activo para mantener la VM viva
    hci0_found = False
    for i in range(15):
        log(f"Waiting for Bluetooth adapter... ({i+1}/15s)")
        try:
            res = subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "test", "-d", "/sys/class/bluetooth/hci0"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
            )
            if res.returncode == 0:
                hci0_found = True
                break
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(1)

    # Solo ahora matamos el proceso de mantenimiento
    try:
        boot_proc.terminate()
    except Exception:
        pass

    if not hci0_found:
        log("Error: Bluetooth adapter (hci0) not detected. Check your USB dongle.")
        return False

    log("Starting D-Bus and bluetoothd in Alpine...")
    try:
        subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "ash", "-c", startup_cmd],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20
        )
    except subprocess.TimeoutExpired:
        pass
    log("Bluetooth ready for scanning/connection.")
    return True

def get_discovered_devices():
    """
    Obtiene la lista de todos los dispositivos (emparejados o descubiertos)
    en el caché de BlueZ consultando directamente a D-Bus ObjectManager.
    Devuelve una lista de tuplas (name, mac).
    """
    try:
        res = subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root",
             "dbus-send", "--system", "--print-reply",
             "--dest=org.bluez", "/",
             "org.freedesktop.DBus.ObjectManager.GetManagedObjects"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
        )
        out = res.stdout
        
        devices = []
        # Dividir la salida por bloques de objeto de D-Bus
        blocks = out.split('object path "')
        for block in blocks:
            if "org.bluez.Device1" not in block:
                continue
                
            # Extraer dirección MAC
            mac_m = re.search(r'variant\s+string\s+"([0-9A-Fa-f:]{17})"', block)
            if not mac_m:
                continue
            mac = mac_m.group(1)
            
            # Extraer nombre (intentar "Name", si no "Alias")
            name = ""
            name_m = re.search(r'string\s+"Name"\s+variant\s+string\s+"([^"]+)"', block)
            if name_m:
                name = name_m.group(1).strip()
            else:
                alias_m = re.search(r'string\s+"Alias"\s+variant\s+string\s+"([^"]+)"', block)
                if alias_m:
                    name = alias_m.group(1).strip()
            
            # Evitar que la dirección MAC sea el nombre
            if name.replace(":", "-").lower() == mac.replace(":", "-").lower():
                name = ""
                
            disp_name = name if name else "Unknown Device"
            devices.append((disp_name, mac))
            
        return devices
    except Exception:
        return []

def run_scan_bg(status_var, listbox, btn_scan, btn_connect):
    try:
        status_var.set("Starting Bluetooth adapter...")
        bt_ok = ensure_bluetooth_active(lambda msg: status_var.set(msg))
        if not bt_ok:
            status_var.set("Could not start Bluetooth adapter. Verify USB dongle.")
            return

        status_var.set("Searching for nearby Bluetooth devices (10s)...")
        # Iniciamos el escaneo interactivo de forma segura para garantizar que el agente se registre y comience la búsqueda
        try:
            subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "ash", "-c",
                 "(echo 'scan on'; sleep 10; echo 'quit') | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=18
            )
        except Exception:
            pass

        # Consultamos el caché completo de D-Bus que incluye los nuevos descubiertos por el escaneo
        devices = get_discovered_devices()
        
        listbox.delete(0, tk.END)
        
        # Eliminar duplicados si los hubiera y ordenar por nombre
        unique_devices = {}
        for name, mac in devices:
            # Si ya existe pero el nuevo nombre es más largo/descriptivo, lo actualizamos
            if mac not in unique_devices or len(name) > len(unique_devices[mac]):
                unique_devices[mac] = name
                
        sorted_devices = sorted(unique_devices.items(), key=lambda x: x[1] if x[1] else x[0])
        
        if not sorted_devices:
            status_var.set("No nearby Bluetooth devices were found.")
        else:
            for mac, name in sorted_devices:
                disp_name = name if name else "Unknown Device"
                listbox.insert(tk.END, f"{disp_name} ({mac})")
            status_var.set(f"Search finished. Found {len(sorted_devices)} devices.")
            
    except Exception as e:
        status_var.set(f"Error searching: {str(e)}")
    finally:
        btn_scan.config(state="normal")
        btn_connect.config(state="normal")

def run_connect_bg(selected_device_str, status_var, btn_scan, btn_connect, win, lbl_current):
    global _start_thread, skip_clean_boot
    
    def get_device_info(target_mac):
        try:
            chk = subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", f"echo 'info {target_mac}' | bluetoothctl"],
                capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=8
            )
            out = chk.stdout
            is_paired = "Paired: yes" in out
            is_trusted = "Trusted: yes" in out
            is_connected = "Connected: yes" in out
            return is_paired, is_trusted, is_connected
        except Exception:
            return False, False, False

    try:
        match = re.search(r"^(.*)\s+\(([0-9A-Fa-f:]{17})\)$", selected_device_str)
        if not match:
            status_var.set("Invalid device selection.")
            return
        name = match.group(1).strip()
        mac = match.group(2).strip()

        # Si el streaming está activo, lo detenemos temporalmente para cambiar de dispositivo de forma limpia
        was_streaming = state in (STATE_STREAMING, STATE_CONNECTING, STATE_BT_WAIT, STATE_STARTING, STATE_ERROR)
        if was_streaming:
            status_var.set("Stopping LDAC streaming to change device...")
            global keep_wsl_alive
            keep_wsl_alive = True
            stop_event.set()
            if _start_thread and _start_thread.is_alive():
                _start_thread.join(timeout=5)
            stop_event.clear()
            keep_wsl_alive = False

        status_var.set("Starting Bluetooth adapter...")
        ensure_bluetooth_active(lambda msg: status_var.set(msg))

        # 1. Obtener estado actual del dispositivo objetivo antes de tomar acciones
        status_var.set("Checking current device status...")
        paired, trusted, connected = get_device_info(mac)

        if connected:
            save_config(mac, name)
            status_var.set(f"{name} is already connected!")
            lbl_current.config(text=f"Current Headphones: {name} ({mac})")
            # Si estaba transmitiendo, reiniciamos la transmisión
            if was_streaming:
                skip_clean_boot = True
                _start_thread = threading.Thread(target=start_ldac, daemon=True)
                _start_thread.start()
                status_var.set(f"{name} is already connected. Stream is restarting...")
            return

        # 2. Buscar y desconectar OTROS dispositivos conectados para liberar el adaptador físico
        status_var.set("Releasing Bluetooth adapter...")
        res_conn = subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", "echo 'devices Connected' | bluetoothctl"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=6
        )
        connected_macs = re.findall(r"Device\s+([0-9A-Fa-f:]{17})", res_conn.stdout)
        if connected_macs:
            for c_mac in connected_macs:
                if c_mac.upper() != mac.upper():
                    status_var.set(f"Disconnecting previous device ({c_mac})...")
                    subprocess.run(
                        ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", f"(sleep 1.2; echo 'disconnect {c_mac}'; sleep 3) | bluetoothctl"],
                        creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10
                    )
                    # Esperar verificación de la desconexión física
                    disc_ok = False
                    for _ in range(5):
                        time.sleep(1)
                        _, _, still_connected = get_device_info(c_mac)
                        if not still_connected:
                            disc_ok = True
                            break
                    if not disc_ok:
                        status_var.set(f"Failed to disconnect previous device {c_mac}.")
                        return
            time.sleep(1.5) # Breve pausa para estabilizar la desconexión del chip de radio

        # 3. Fase de Emparejamiento (Pair) dinámico si no está emparejado
        if not paired:
            status_var.set(f"Pairing with {name} (put it in pairing mode)...")
            subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", f"(sleep 1.2; echo 'pair {mac}'; sleep 8) | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=15
            )
            time.sleep(1)

        # 4. Fase de Confianza (Trust)
        if not trusted:
            status_var.set(f"Configuring trust for {name}...")
            subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", f"(sleep 1.2; echo 'trust {mac}'; sleep 1) | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=8
            )
            time.sleep(0.5)

        # 5. Fase de Conexión (Connect)
        status_var.set(f"Connecting to {name}...")
        # Dejamos bluetoothctl abierto 8 segundos para iniciar el enlace A2DP de forma segura y completa
        subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", f"(sleep 1.2; echo 'connect {mac}'; sleep 8) | bluetoothctl"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=15
        )
        
        # Una pequeña espera adicional y verificar estado real de conexión
        time.sleep(1)
        _, _, final_conn = get_device_info(mac)
        
        if final_conn:
            save_config(mac, name)
            
            # Ajustar volumen en Alpine al 80%
            subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", 
                 "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl set-sink-volume @DEFAULT_SINK@ 80%"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
            )
            
            status_var.set(f"Successful connection to {name}!")
            lbl_current.config(text=f"Current Headphones: {name} ({mac})")
            show_notification("Bluetooth LDAC", f"Device {name} connected successfully.")

            # Si estaba transmitiendo, reiniciamos automáticamente la transmisión LDAC con el nuevo dispositivo
            if was_streaming:
                skip_clean_boot = True
                _start_thread = threading.Thread(target=start_ldac, daemon=True)
                _start_thread.start()
                status_var.set(f"Connected to {name}. Stream is restarting — watch the tray icon.")
        else:
            status_var.set("Connection error. Please retry or power on the device.")
            
    except Exception as e:
        status_var.set(f"Connection error: {str(e)}")
    finally:
        btn_scan.config(state="normal")
        btn_connect.config(state="normal")

_bt_window = None

def show_bluetooth_window(icon=None, item=None):
    global _bt_window
    
    try:
        if _bt_window and _bt_window.winfo_exists():
            _bt_window.lift()
            _bt_window.focus_force()
            return
    except Exception:
        _bt_window = None

    # Paleta de colores premium oscuros y cian
    BG        = "#0d0d1a"
    CARD      = "#161628"
    ACCENT    = "#00e5ff"
    TEXT      = "#e8e8f0"
    MUTED     = "#6868a0"
    GREEN     = "#00ff88"
    YELLOW    = "#f0c040"

    win = tk.Tk()
    win.title("Bluetooth Device Manager")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    W, H = 400, 540
    win.geometry(f"{W}x{H}+{(win.winfo_screenwidth()-W)//2}+{(win.winfo_screenheight()-H)//2}")

    # Header Accent line
    hdr = tk.Frame(win, bg=ACCENT, height=4)
    hdr.pack(fill="x")

    # Title labels
    tk.Label(win, text="Configure Bluetooth Device",
             bg=BG, fg=ACCENT,
             font=("Segoe UI", 12, "bold")).pack(pady=(12, 2))
    
    config = load_config()
    current_name = config.get("selected_name", "Wireless Headphones")
    current_mac = config.get("selected_mac", "01:02:03:04:1E:19")
    
    lbl_current = tk.Label(win, text=f"Current Headphones: {current_name} ({current_mac})",
                           bg=BG, fg=MUTED, font=("Segoe UI", 9, "italic"))
    lbl_current.pack(pady=(0, 6))

    # Definición de limpieza de caché en segundo plano
    def on_clear_devices():
        if not messagebox.askyesno("Confirm", "Are you sure you want to clear and unpair all saved Bluetooth devices?"):
            return
        
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        btn_clear.config(state="disabled")
        v_status.set("Cleaning device cache...")
        
        def run_clear_bg():
            try:
                ensure_bluetooth_active(lambda msg: v_status.set(msg))
                
                # Obtener todos los conocidos
                res = subprocess.run(
                    ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", "echo 'devices' | bluetoothctl"],
                    capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10
                )
                macs = re.findall(r"Device\s+([0-9A-Fa-f:]{17})", res.stdout)
                
                if macs:
                    for target_mac in macs:
                        v_status.set(f"Removing {target_mac}...")
                        subprocess.run(
                            ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", f"echo 'remove {target_mac}' | bluetoothctl"],
                            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=6
                        )
                
                # Guardar config vacía/default
                save_config("01:02:03:04:1E:19", "Wireless Headphones", "hq")
                
                listbox.delete(0, tk.END)
                lbl_current.config(text="Current Headphones: Wireless Headphones (01:02:03:04:1E:19)")
                v_status.set("Device cache cleared successfully!")
            except Exception as e:
                v_status.set(f"Error clearing: {str(e)}")
            finally:
                btn_scan.config(state="normal")
                btn_connect.config(state="normal")
                btn_clear.config(state="normal")
                
        threading.Thread(target=run_clear_bg, daemon=True).start()

    # Frame para listbox y scrollbar
    frame_list = tk.Frame(win, bg=CARD, bd=1, relief="flat", padx=10, pady=10)
    frame_list.pack(fill="both", expand=True, padx=18, pady=5)

    frame_list_header = tk.Frame(frame_list, bg=CARD)
    frame_list_header.pack(fill="x", pady=(0, 5))
    
    tk.Label(frame_list_header, text="Available Devices:", bg=CARD, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side="left")
    
    btn_clear = tk.Button(frame_list_header, text="🧹 Clear All", command=on_clear_devices,
                          bg="#2c2c3e", fg=MUTED, activebackground="#ff4444", activeforeground=TEXT,
                          relief="flat", font=("Segoe UI", 8), cursor="hand2", padx=6, pady=1)
    btn_clear.pack(side="right")

    scrollbar = tk.Scrollbar(frame_list, orient="vertical")
    listbox = tk.Listbox(frame_list, yscrollcommand=scrollbar.set,
                         bg="#101020", fg=TEXT, selectbackground=ACCENT, selectforeground=BG,
                         highlightthickness=0, font=("Segoe UI", 9), bd=0)
    scrollbar.config(command=listbox.yview)
    scrollbar.pack(side="right", fill="y")
    listbox.pack(side="left", fill="both", expand=True)

    try:
        known = get_discovered_devices()
        for name, mac in known:
            listbox.insert(tk.END, f"{name} ({mac})")
    except Exception:
        pass

    # Frame para Calidad
    frame_quality = tk.Frame(win, bg=CARD, bd=1, relief="flat", padx=10, pady=8)
    frame_quality.pack(fill="x", padx=18, pady=5)
    
    tk.Label(frame_quality, text="LDAC Audio Quality:", bg=CARD, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 5))
    
    v_mode = tk.StringVar(master=win, value=config.get("ldac_mode", "hq"))
    win.v_mode = v_mode  # Prevenir Garbage Collection (hilo secundario)
    
    def on_mode_change():
        cfg = load_config()
        save_config(cfg["selected_mac"], cfg["selected_name"], v_mode.get())
        v_status.set(f"Mode saved: {v_mode.get().upper()}. Restart the app to apply.")
    
    r_hq = tk.Radiobutton(frame_quality, text="🟢 Extreme Quality (990 kbps)", variable=v_mode, value="hq",
                          bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=ACCENT,
                          selectcolor=CARD, font=("Segoe UI", 9), command=on_mode_change, cursor="hand2")
    r_hq.pack(anchor="w", pady=2)
    
    r_sq = tk.Radiobutton(frame_quality, text="🟡 Stable Mode (660 kbps)", variable=v_mode, value="sq",
                          bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=ACCENT,
                          selectcolor=CARD, font=("Segoe UI", 9), command=on_mode_change, cursor="hand2")
    r_sq.pack(anchor="w", pady=2)
    
    r_auto = tk.Radiobutton(frame_quality, text="🔵 Adaptive Mode (Auto)", variable=v_mode, value="auto",
                            bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=ACCENT,
                            selectcolor=CARD, font=("Segoe UI", 9), command=on_mode_change, cursor="hand2")
    r_auto.pack(anchor="w", pady=2)

    # Estado de progreso
    v_status = tk.StringVar(master=win, value="Ready.")
    win.v_status = v_status  # Prevenir Garbage Collection (hilo secundario)
    status_bar = tk.Label(win, textvariable=v_status, bg=BG, fg=YELLOW,
                          font=("Segoe UI", 9), wraplength=360, justify="center")
    status_bar.pack(pady=5, padx=18)

    # Frame para botones
    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(fill="x", padx=18, pady=(5, 12))

    def on_scan():
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        threading.Thread(target=run_scan_bg, args=(v_status, listbox, btn_scan, btn_connect), daemon=True).start()

    def on_connect():
        sel = listbox.curselection()
        if not sel:
            v_status.set("Please select a device from the list.")
            return
        selected_str = listbox.get(sel[0])
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        threading.Thread(target=run_connect_bg, args=(selected_str, v_status, btn_scan, btn_connect, win, lbl_current), daemon=True).start()

    btn_scan = tk.Button(btn_frame, text="🔍 Scan Devices", command=on_scan,
                         bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                         relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=10)
    btn_scan.pack(side="left", fill="x", expand=True, padx=(0, 5))

    btn_connect = tk.Button(btn_frame, text="🔗 Connect", command=on_connect,
                            bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                            relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=10)
    btn_connect.pack(side="left", fill="x", expand=True, padx=(5, 5))

    def on_close():
        global _bt_window
        _bt_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    btn_close = tk.Button(btn_frame, text="✕ Close", command=on_close,
                          bg=CARD, fg=MUTED, activebackground="#ff4444", activeforeground=TEXT,
                          relief="flat", font=("Segoe UI", 9), cursor="hand2", padx=10)
    btn_close.pack(side="left", fill="x", expand=True, padx=(5, 0))

    _bt_window = win
    win.mainloop()

# Estados del sistema
STATE_STOPPED    = "Stopped"
STATE_STARTING   = "Starting..."
STATE_BT_WAIT    = "Waiting for Bluetooth..."
STATE_CONNECTING = "Connecting headphones..."
STATE_STREAMING  = "Streaming LDAC"
STATE_STOPPING   = "Stopping..."
STATE_ERROR      = "Error"

# ---------------------------------------------------------------------------
# Estado compartido entre hilos
# ---------------------------------------------------------------------------
state        = STATE_STOPPED
python_proc  = None
wsl_proc     = None
stop_event   = threading.Event()
tray_icon    = None
keep_wsl_alive = False
skip_clean_boot = False

# ---------------------------------------------------------------------------
# Generador de iconos dinamicos con Pillow
# ---------------------------------------------------------------------------
def make_icon(color_inner="#00e5ff", color_outer="#1a1a2e", label=""):
    """
    Genera un icono cuadrado de 64x64 px con un circulo de color y
    una letra indicadora del estado (S=streaming, X=stopped, ...).
    """
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fondo circular oscuro
    draw.ellipse([2, 2, size - 2, size - 2], fill=color_outer)
    # Circulo interior de color
    draw.ellipse([10, 10, size - 10, size - 10], fill=color_inner)

    # Letra central (sin fuente externa para no tener dependencias)
    if label:
        bbox = draw.textbbox((0, 0), label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            ((size - tw) / 2, (size - th) / 2 - 2),
            label,
            fill="white",
        )
    return img


ICONS = {
    STATE_STOPPED:    make_icon("#444466", "#1a1a2e", ""),
    STATE_STARTING:   make_icon("#f0a500", "#1a1a2e", ""),
    STATE_BT_WAIT:    make_icon("#f0a500", "#1a1a2e", ""),
    STATE_CONNECTING: make_icon("#f0a500", "#1a1a2e", ""),
    STATE_STREAMING:  make_icon("#00e5ff", "#1a1a2e", ""),
    STATE_STOPPING:   make_icon("#f0a500", "#1a1a2e", ""),
    STATE_ERROR:      make_icon("#ff4444", "#1a1a2e", ""),
}

# ---------------------------------------------------------------------------
# Helpers de subprocesos
# ---------------------------------------------------------------------------
# Flag de Windows para suprimir cualquier ventana de consola emergente
CREATE_NO_WINDOW = 0x08000000


def _startupinfo():
    """STARTUPINFO con ventana oculta para subprocesos de Windows."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def run(cmd, **kwargs):
    """Ejecuta un comando y silencia su salida sin mostrar ventana."""
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        startupinfo=_startupinfo(),
        **kwargs
    )


def set_state(new_state):
    global state
    state = new_state
    if tray_icon:
        tray_icon.icon    = ICONS.get(new_state, ICONS[STATE_STOPPED])
        tray_icon.title   = f"LDAC Audio — {new_state}"
        rebuild_menu()


def rebuild_menu():
    if tray_icon is None:
        return
    is_running = state == STATE_STREAMING
    tray_icon.menu = build_menu(is_running)

# ---------------------------------------------------------------------------
# Logica principal: arranque / parada en hilos
# ---------------------------------------------------------------------------
def start_ldac():
    """Hilo que ejecuta toda la secuencia de arranque LDAC."""
    global python_proc, wsl_proc, skip_clean_boot

    get_dynamic_busid()
    stop_event.clear()

    try:
        # Asegurar servicio de Windows iniciado
        ensure_usbipd_service()
        
        # 0. Limpieza previa: garantizar estado limpio sin importar como se cerro antes
        set_state(STATE_STARTING)
        if not skip_clean_boot:
            run([USBIPD, "detach", "--busid", BUSID])   # no-op si ya estaba desconectado
            run(["wsl", "--shutdown"])                   # asegurar Alpine apagado limpio
            time.sleep(1)
        else:
            skip_clean_boot = False

        # 1. Bind USBIPD
        ensure_device_bound()


        # 2. Pre-cargar modulos del kernel en Alpine
        run(["wsl", "-d", "Alpine", "-u", "root", "modprobe", "vhci-hcd"])
        run(["wsl", "-d", "Alpine", "-u", "root", "modprobe", "btusb"])
        
        # Copiar y dar permisos al script receptor de audio actualizado
        receptor_local = os.path.join(INSTALL_DIR, "receptor_audio.sh")
        if os.path.exists(receptor_local):
            try:
                content = open(receptor_local, "r", encoding="utf-8").read()
                proc = subprocess.Popen(
                    ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c", "cat > /root/receptor_audio.sh"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
                )
                proc.communicate(input=content.encode("utf-8"), timeout=5)
            except Exception:
                pass
        run(["wsl", "-d", "Alpine", "-u", "root", "chmod", "+x", "/root/receptor_audio.sh"])
        time.sleep(1)

        # Mantener viva la distribución durante el attach
        boot_proc = subprocess.Popen(["wsl", "-d", "Alpine", "-u", "root", "sleep", "10"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo())
        time.sleep(1)

        # 3. Attach USBIPD
        run([USBIPD, "attach", "--wsl", "Alpine", "--busid", BUSID])

        try:
            boot_proc.terminate()
        except Exception:
            pass

        # 4. Iniciar receptor de audio en Alpine (sin ventana visible)
        set_state(STATE_BT_WAIT)
        config = load_config()
        selected_mac = config.get("selected_mac", "01:02:03:04:1E:19")
        ldac_mode = config.get("ldac_mode", "hq")
        wsl_proc = subprocess.Popen(
            ["wsl", "-d", "Alpine", "-u", "root", "ash", "-c",
             f"/root/receptor_audio.sh {selected_mac} {ldac_mode}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )

        # 5. Esperar a que hci0 aparezca en el kernel (max 15s)
        set_state(STATE_CONNECTING)
        for _ in range(15):
            if stop_event.is_set():
                return
            result = subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "test", "-d",
                 "/sys/class/bluetooth/hci0"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=_startupinfo(),
            )
            if result.returncode == 0:
                break
            time.sleep(1)

        # 6. Iniciar el emisor Python en Windows (sin ventana)
        python_proc = subprocess.Popen(
            [sys.executable, EMISOR_PY],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )

        # 7. Esperar a que PipeWire detecte el sink Bluetooth (auriculares conectados)
        #    Consultamos pactl cada 2s hasta que aparezca el sink bluez (max 30s)
        bluez_found = False
        for _ in range(15):
            if stop_event.is_set():
                return
            check = subprocess.run(
                ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c",
                 "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native "
                 "pactl list sinks short 2>/dev/null"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=_startupinfo(),
            )
            if "bluez" in check.stdout:
                bluez_found = True
                break
            time.sleep(2)

        if bluez_found:
            set_state(STATE_STREAMING)
        else:
            set_state(STATE_ERROR)
            show_notification("LDAC", "No Bluetooth device connected. Open Configure Bluetooth to pair your headphones.")
            return

        # Mantener el hilo vivo y monitorear la salud de los procesos
        while not stop_event.is_set():
            if wsl_proc and wsl_proc.poll() is not None:
                break
            if python_proc and python_proc.poll() is not None:
                break
            time.sleep(1)

    except Exception as e:
        set_state(STATE_ERROR)
        show_notification("LDAC Error", str(e))
    finally:
        stop_ldac_cleanup()


def stop_ldac_cleanup():
    """Limpieza de todos los recursos (se llama desde el hilo de arranque)."""
    global python_proc, wsl_proc

    get_dynamic_busid()
    set_state(STATE_STOPPING)

    # Matar emisor Python
    if python_proc and python_proc.poll() is None:
        python_proc.terminate()
        try:
            python_proc.wait(timeout=3)
        except Exception:
            python_proc.kill()
    python_proc = None

    # Matar proceso receptor WSL si sigue vivo
    if wsl_proc and wsl_proc.poll() is None:
        wsl_proc.terminate()
    wsl_proc = None

    # Si no queremos mantener WSL vivo (apagado/detener completo tradicional)
    if not keep_wsl_alive:
        # Detach USBIPD
        run([USBIPD, "detach", "--busid", BUSID])
        # Apagar WSL
        run(["wsl", "--shutdown"])
    else:
        # Si queremos mantenerlo vivo, solo limpiamos procesos residuales de audio en Alpine
        run(["wsl", "-d", "Alpine", "-u", "root", "killall", "-9", "nc", "pacat"])

    set_state(STATE_STOPPED)


# ---------------------------------------------------------------------------
# Ventana de monitoreo en tiempo real
# ---------------------------------------------------------------------------
_info_window = None


def _get_ldac_bitrate():
    """
    Consulta el bitrate/calidad LDAC real negociado u obtenido de PipeWire/configuración.
    Devuelve una tupla (label, color).
    """
    try:
        # 1. Consultamos pactl para saber si el códec activo es LDAC y ver si tiene la propiedad de calidad
        result = subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c",
             "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl list sinks 2>/dev/null"],
            capture_output=True, text=True, timeout=4,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(),
        )
        out = result.stdout
        
        # Comprobar si el codec activo es LDAC
        import re as _re
        is_ldac = "ldac" in out.lower()
        
        if is_ldac:
            # Intentar extraer la calidad de las propiedades de PipeWire
            m_qual = _re.search(r'bluez5\.a2dp\.ldac\.quality\s*=\s*"([^"]+)"', out)
            quality = m_qual.group(1) if m_qual else None
            
            # Si no está en las propiedades del sink de pactl, recurrimos a ldac_config.json
            if not quality:
                config = load_config()
                quality = config.get("ldac_mode", "hq")
                
            # Mapeamos la calidad al label y color correspondientes
            if quality == "hq":
                return "990 kbps", "#00ff88"      # Verde para HQ (Calidad Extrema)
            elif quality == "sq":
                return "660 kbps", "#f0c040"      # Amarillo para SQ (Modo Estable)
            elif quality == "mq":
                return "330 kbps", "#ff6644"      # Naranja/Rojo para MQ (Modo Móvil)
            elif quality == "auto":
                return "Adaptive (Auto)", "#00e5ff"  # Cian para Adaptativo
                
    except Exception:
        pass
        
    return "?", "#888888"


def _get_pipewire_info():
    """
    Consulta pactl en Alpine y devuelve (device_name, codec, ldac_kbps).
    Se ejecuta en un hilo para no bloquear la UI.
    """
    try:
        result = subprocess.run(
            ["wsl", "-d", "Alpine", "-u", "root", "sh", "-c",
             "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native "
             "pactl list sinks 2>/dev/null"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )
        out = result.stdout

        # Nombre del dispositivo
        import re as _re
        name_m  = _re.search(r'device\.description = "([^"]+)"', out)
        codec_m = _re.search(r'api\.bluez5\.codec = "([^"]+)"', out)

        device  = name_m.group(1)  if name_m  else "Unknown"
        codec   = codec_m.group(1).upper() if codec_m else "?"
        return device, codec
    except Exception:
        return "No connection", "?"


def show_info_window(icon=None, item=None):
    """Abre (o trae al frente) la ventana de monitoreo."""
    global _info_window

    try:
        if _info_window and _info_window.winfo_exists():
            _info_window.lift()
            _info_window.focus_force()
            return
    except Exception:
        _info_window = None

    # ------- Paleta de colores -------
    BG        = "#0d0d1a"
    CARD      = "#161628"
    ACCENT    = "#00e5ff"
    TEXT      = "#e8e8f0"
    MUTED     = "#6868a0"
    GREEN     = "#00ff88"
    YELLOW    = "#f0c040"

    win = tk.Tk()
    win.title("LDAC Monitor")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    # Centrar en pantalla
    W, H = 360, 310
    win.geometry(f"{W}x{H}+{(win.winfo_screenwidth()-W)//2}+{(win.winfo_screenheight()-H)//2}")

    # ---- Header ----
    hdr = tk.Frame(win, bg=ACCENT, height=4)
    hdr.pack(fill="x")

    tk.Label(win, text="LDAC Audio Monitor",
             bg=BG, fg=ACCENT,
             font=("Segoe UI", 13, "bold")).pack(pady=(14, 2))
    tk.Label(win, text="Real-time Statistics",
             bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack()

    # ---- Tarjeta de informacion ----
    card = tk.Frame(win, bg=CARD, padx=20, pady=14)
    card.pack(fill="x", padx=18, pady=10)

    def row(parent, label, var, value_color=TEXT):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=3)
        tk.Label(f, text=label, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side="left")
        lbl = tk.Label(f, textvariable=var, bg=CARD, fg=value_color,
                       font=("Segoe UI", 9, "bold"), anchor="w")
        lbl.pack(side="left")
        return lbl

    v_device  = tk.StringVar(master=win, value="Querying...")
    v_codec   = tk.StringVar(master=win, value="...")
    v_ldac    = tk.StringVar(master=win, value="--- kbps")
    v_udp     = tk.StringVar(master=win, value="--- kbps")
    v_volume  = tk.StringVar(master=win, value="---%")
    v_status  = tk.StringVar(master=win, value=state)
    
    # Prevenir Garbage Collection en Tkinter (hilo secundario)
    win.v_device = v_device
    win.v_codec = v_codec
    win.v_ldac = v_ldac
    win.v_udp = v_udp
    win.v_volume = v_volume
    win.v_status = v_status

    row(card, "Device",  v_device)
    row(card, "Codec",        v_codec,  ACCENT)
    ldac_row_lbl = row(card, "LDAC bitrate", v_ldac, GREEN)
    row(card, "UDP stream",   v_udp,    YELLOW)
    row(card, "Volume",      v_volume)

    # ---- Separador ----
    sep = tk.Frame(win, bg=MUTED, height=1)
    sep.pack(fill="x", padx=18)

    # ---- Barra de estado ----
    status_frame = tk.Frame(win, bg=BG)
    status_frame.pack(fill="x", padx=18, pady=6)
    dot = tk.Label(status_frame, text="●", bg=BG, fg=ACCENT,
                   font=("Segoe UI", 10))
    dot.pack(side="left")
    tk.Label(status_frame, textvariable=v_status, bg=BG, fg=TEXT,
             font=("Segoe UI", 9)).pack(side="left", padx=4)

    def on_close():
        global _info_window
        _info_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    # ---- Boton cerrar ----
    tk.Button(win, text="Close", command=on_close,
              bg=CARD, fg=MUTED, relief="flat",
              font=("Segoe UI", 8),
              activebackground=ACCENT, activeforeground=BG,
              cursor="hand2").pack(pady=(2, 10))

    # ---- Loop de actualizacion ----
    # Contadores de refresco independientes
    _pipewire_cache           = [None, None]  # [device, codec]
    _pipewire_refresh_counter = [0]
    _ldac_refresh_counter     = [0]
    _ldac_cache               = ["--- kbps", "#888888"]

    def refresh_pipewire():
        d, c = _get_pipewire_info()
        _pipewire_cache[0] = d
        _pipewire_cache[1] = c

    def refresh_ldac_bitrate():
        label, color = _get_ldac_bitrate()
        _ldac_cache[0] = label
        _ldac_cache[1] = color

    # Primera consulta de ambos en hilos
    threading.Thread(target=refresh_pipewire,    daemon=True).start()
    threading.Thread(target=refresh_ldac_bitrate, daemon=True).start()

    def update_ui():
        if not win.winfo_exists():
            return
        try:
            # Estado general
            v_status.set(state)
            dot.config(fg=ACCENT if state == STATE_STREAMING else
                        YELLOW if state != STATE_STOPPED else MUTED)

            # Estadisticas UDP del emisor
            try:
                with open(STATS_FILE) as f:
                    stats = json.load(f)
                if time.time() - stats.get("timestamp", 0) < 3:
                    v_udp.set(f"{stats['udp_kbps']} kbps")
                    v_volume.set(f"{stats['volume']}%")
                else:
                    v_udp.set("--- kbps")
            except Exception:
                v_udp.set("--- kbps")

            # Refresco info PipeWire cada 5s
            _pipewire_refresh_counter[0] += 1
            if _pipewire_refresh_counter[0] >= 5:
                _pipewire_refresh_counter[0] = 0
                threading.Thread(target=refresh_pipewire, daemon=True).start()

            if _pipewire_cache[0]:
                v_device.set(_pipewire_cache[0])
                v_codec.set(_pipewire_cache[1])

            # Refresco bitrate LDAC real cada 3s con color dinamico
            _ldac_refresh_counter[0] += 1
            if _ldac_refresh_counter[0] >= 3:
                _ldac_refresh_counter[0] = 0
                threading.Thread(target=refresh_ldac_bitrate, daemon=True).start()

            v_ldac.set(_ldac_cache[0])
            ldac_row_lbl.config(fg=_ldac_cache[1])

            win.after(1000, update_ui)
        except tk.TclError:
            pass

    win.after(1000, update_ui)
    _info_window = win
    win.mainloop()


_start_thread = None


def action_start(icon, item):
    global _start_thread
    if state not in (STATE_STOPPED, STATE_ERROR):
        return
    _start_thread = threading.Thread(target=start_ldac, daemon=True)
    _start_thread.start()


def action_stop(icon, item):
    if state == STATE_STOPPED:
        return
    stop_event.set()


def action_status(icon, item):
    show_notification("LDAC Status", f"Current status: {state}")


def action_quit(icon, item):
    """Detener todo y salir de la aplicacion de forma limpia y completa."""
    # 1. Señalar parada a los hilos de audio
    stop_event.set()
    if _start_thread and _start_thread.is_alive():
        _start_thread.join(timeout=5)
        
    # 2. Matar procesos residuales de emisor/receptor si siguen vivos
    global python_proc, wsl_proc
    try:
        if python_proc and python_proc.poll() is None:
            python_proc.terminate()
            python_proc.wait(timeout=2)
    except Exception:
        try:
            python_proc.kill()
        except Exception:
            pass
    python_proc = None

    try:
        if wsl_proc and wsl_proc.poll() is None:
            wsl_proc.terminate()
    except Exception:
        pass
    wsl_proc = None

    # 3. Liberar hardware Bluetooth y apagar WSL incondicionalmente
    try:
        subprocess.run([USBIPD, "detach", "--busid", BUSID],
                       creationflags=CREATE_NO_WINDOW,
                       startupinfo=_startupinfo(),
                       timeout=3)
    except Exception:
        pass
    try:
        subprocess.run(["wsl", "--shutdown"],
                       creationflags=CREATE_NO_WINDOW,
                       startupinfo=_startupinfo(),
                       timeout=5)
    except Exception:
        pass

    # 4. Detener el icono de la bandeja
    try:
        icon.stop()
    except Exception:
        pass

    cleanup_pid_file()


def action_force_quit(icon, item):
    """Salida de emergencia: mata todos los procesos y cierra sin esperar."""
    try:
        # Matar emisor Python si existe
        if python_proc and python_proc.poll() is None:
            python_proc.kill()
    except Exception:
        pass
    try:
        # Matar proceso WSL si existe
        if wsl_proc and wsl_proc.poll() is None:
            wsl_proc.kill()
    except Exception:
        pass
    try:
        # Detach USBIPD y apagar WSL por las malas
        subprocess.run([USBIPD, "detach", "--busid", BUSID],
                       creationflags=CREATE_NO_WINDOW,
                       startupinfo=_startupinfo(),
                       timeout=3)
        subprocess.run(["wsl", "--shutdown"],
                       creationflags=CREATE_NO_WINDOW,
                       startupinfo=_startupinfo(),
                       timeout=5)
    except Exception:
        pass
    try:
        icon.stop()
    except Exception:
        pass
    # Salida garantizada sin importar el estado de los hilos
    os._exit(0)


def show_notification(title, message):
    if tray_icon:
        tray_icon.notify(message, title)


# ---------------------------------------------------------------------------
# Context menu construction
# ---------------------------------------------------------------------------
def build_menu(is_running=False):
    items = []

    if is_running:
        items.append(pystray.MenuItem("⏹  Stop LDAC", action_stop))
    else:
        items.append(pystray.MenuItem("▶  Start LDAC", action_start,
                                      default=True))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(
        "📊  View Statistics",
        lambda icon, item: threading.Thread(
            target=show_info_window, daemon=True
        ).start()
    ))
    items.append(pystray.MenuItem(
        "🎧  Configure Bluetooth",
        lambda icon, item: threading.Thread(
            target=show_bluetooth_window, daemon=True
        ).start()
    ))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(f"Status: {state}", action_status,
                                   enabled=False))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("✕  Exit", action_quit))
    items.append(pystray.MenuItem("⚡ Force Exit", action_force_quit))

    return pystray.Menu(*items)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    check_single_instance()
    global tray_icon

    tray_icon = pystray.Icon(
        name="ldac_audio",
        icon=ICONS[STATE_STOPPED],
        title="LDAC Audio — Stopped",
        menu=build_menu(False),
    )

    # Auto-start LDAC on launch — store in _start_thread so restarts can join it
    global _start_thread
    _start_thread = threading.Thread(target=start_ldac, daemon=True)
    _start_thread.start()

    tray_icon.run()


if __name__ == "__main__":
    main()
