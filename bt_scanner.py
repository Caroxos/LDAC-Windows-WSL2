import re
import time
import tkinter as tk
import subprocess
from logger import log_message, run_logged, log_scan_results, WSL_DISTRO, WSL_USER
from sys_helpers import CREATE_NO_WINDOW, _startupinfo, safe_gui_call
from wsl_manager import ensure_bluetooth_active

def get_wsl_paired_devices():
    """Consulta de forma directa los dispositivos Bluetooth emparejados."""
    devices = []
    try:
        res = run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", 
             'for f in /var/lib/bluetooth/*/*/info; do [ -f "$f" ] && echo "FILE:$f" && cat "$f"; done'],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=6
        )
        stdout_str = res.stdout.decode("utf-8", errors="replace")
        if res.returncode == 0 and stdout_str.strip():
            current_mac = None
            current_name = None
            
            for line in stdout_str.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("FILE:"):
                    if current_mac:
                        devices.append((current_name if current_name else "Unknown Device", current_mac))
                    current_mac = None
                    current_name = None
                    
                    path_part = line.replace("FILE:", "")
                    path_parts = path_part.split('/')
                    if len(path_parts) >= 2:
                        mac = path_parts[-2]
                        mac_fmt = mac.replace("_", ":").upper()
                        if re.match(r"^[0-9A-Fa-f:]{17}$", mac_fmt):
                            current_mac = mac_fmt
                elif line.startswith("Name=") and current_mac:
                    current_name = line.split("Name=", 1)[1].strip()
            
            if current_mac:
                devices.append((current_name if current_name else "Unknown Device", current_mac))
    except Exception as e:
        log_message(f"get_wsl_paired_devices error: {str(e)}")
    return devices

def get_discovered_devices():
    """Obtiene la lista de todos los dispositivos en el caché de BlueZ de D-Bus."""
    try:
        res = run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER,
             "dbus-send", "--system", "--print-reply",
             "--dest=org.bluez", "/",
             "org.freedesktop.DBus.ObjectManager.GetManagedObjects"],
            timeout=15,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
        )
        out = res.stdout.decode("utf-8", errors="replace")
        
        devices = []
        blocks = out.split('object path "')
        for block in blocks:
            if "org.bluez.Device1" not in block:
                continue
                
            mac_m = re.search(r'string\s+"Address"\s+variant\s+string\s+"([0-9A-Fa-f:]{17})"', block)
            if not mac_m:
                mac_m = re.search(r'variant\s+string\s+"([0-9A-Fa-f:]{17})"', block)
            if not mac_m:
                continue
            mac = mac_m.group(1).upper()
            
            name = ""
            name_m = re.search(r'string\s+"Name"\s+variant\s+string\s+"([^"]+)"', block)
            if name_m:
                name = name_m.group(1).strip()
            else:
                alias_m = re.search(r'string\s+"Alias"\s+variant\s+string\s+"([^"]+)"', block)
                if alias_m:
                    name = alias_m.group(1).strip()
            
            if name.replace(":", "-").lower() == mac.replace(":", "-").lower():
                name = ""
                
            disp_name = name if name else "Unknown Device"
            devices.append((disp_name, mac))
            
        # Volcar a debug.json para diagnóstico del usuario
        log_scan_results(devices)
        return devices
    except Exception as e:
        log_message(f"get_discovered_devices error: {str(e)}")
        return []

def get_wsl_connected_devices():
    """Obtiene la lista de todos los dispositivos Bluetooth conectados físicamente en WSL."""
    try:
        res = run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER,
             "dbus-send", "--system", "--print-reply",
             "--dest=org.bluez", "/",
             "org.freedesktop.DBus.ObjectManager.GetManagedObjects"],
            timeout=5,
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
        )
        if res.returncode != 0:
            return []
            
        out = res.stdout.decode("utf-8", errors="replace")
        devices = []
        blocks = out.split('object path "')
        for block in blocks:
            if "org.bluez.Device1" not in block:
                continue
            
            connected_match = re.search(r'string\s+"Connected"\s+variant\s+boolean\s+true', block)
            if not connected_match:
                continue
                
            mac_m = re.search(r'string\s+"Address"\s+variant\s+string\s+"([0-9A-Fa-f:]{17})"', block)
            if not mac_m:
                mac_m = re.search(r'variant\s+string\s+"([0-9A-Fa-f:]{17})"', block)
            if not mac_m:
                continue
            mac = mac_m.group(1).upper()
            
            name = ""
            name_m = re.search(r'string\s+"Name"\s+variant\s+string\s+"([^"]+)"', block)
            if name_m:
                name = name_m.group(1).strip()
            else:
                alias_m = re.search(r'string\s+"Alias"\s+variant\s+string\s+"([^"]+)"', block)
                if alias_m:
                    name = alias_m.group(1).strip()
            
            if name.replace(":", "-").lower() == mac.replace(":", "-").lower():
                name = ""
                
            disp_name = name if name else "Unknown Device"
            devices.append((disp_name, mac))
        return devices
    except Exception as e:
        log_message(f"get_wsl_connected_devices error: {str(e)}")
        return []

def run_scan_bg(ctx, status_var, listbox, btn_scan, btn_connect, btn_disconnect=None):
    """Lógica de búsqueda de dispositivos en segundo plano."""
    try:
        safe_gui_call(listbox, lambda: status_var.set("Starting Bluetooth adapter..."))
        bt_ok = ensure_bluetooth_active(ctx, lambda msg: safe_gui_call(listbox, lambda: status_var.set(msg)))
        if not bt_ok:
            safe_gui_call(listbox, lambda: status_var.set("Could not start Bluetooth adapter. Verify USB dongle."))
            return

        safe_gui_call(listbox, lambda: status_var.set("Verifying adapter is powered on..."))
        try:
            pwr_check = run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "ash", "-c",
                 "bluetoothctl show 2>/dev/null | grep -q 'Powered: yes'"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
            )
            if pwr_check.returncode != 0:
                run_logged(
                    ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "ash", "-c",
                     "hciconfig hci0 up 2>/dev/null; "
                     "for i in 1 2 3; do bluetoothctl power on 2>/dev/null && break; sleep 1; done"],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10
                )
                time.sleep(1)
        except Exception:
            pass

        safe_gui_call(listbox, lambda: status_var.set("Searching for nearby Bluetooth devices (12s)..."))
        try:
            run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "bluetoothctl", "--timeout", "12", "scan", "on"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20
            )
        except Exception:
            pass

        devices = get_discovered_devices()
        
        def update_listbox():
            listbox.delete(0, tk.END)
            unique_devices = {}
            for name, mac in devices:
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
                
        safe_gui_call(listbox, update_listbox)
            
    except Exception as e:
        safe_gui_call(listbox, lambda: status_var.set(f"Error searching: {str(e)}"))
    finally:
        safe_gui_call(btn_scan, lambda: btn_scan.config(state="normal"))
        safe_gui_call(btn_connect, lambda: btn_connect.config(state="normal"))
        if btn_disconnect:
            safe_gui_call(btn_disconnect, lambda: btn_disconnect.config(state="normal"))

def run_connect_bg(ctx, selected_device_str, status_var, btn_scan, btn_connect, win, lbl_current, btn_disconnect=None):
    """Lógica de conexión Bluetooth en segundo plano."""
    from context import STATE_STREAMING, STATE_CONNECTING, STATE_BT_WAIT, STATE_STARTING
    
    def get_device_info(target_mac):
        try:
            chk = run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"echo 'info {target_mac}' | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=8
            )
            out = chk.stdout.decode("utf-8", errors="replace")
            is_paired = "Paired: yes" in out
            is_trusted = "Trusted: yes" in out
            is_connected = "Connected: yes" in out
            return is_paired, is_trusted, is_connected
        except Exception:
            return False, False, False

    try:
        match = re.search(r"^(.*)\s+\(([0-9A-Fa-f:]{17})\)$", selected_device_str)
        if not match:
            safe_gui_call(win, lambda: status_var.set("Invalid device selection."))
            return
        name = match.group(1).strip()
        mac = match.group(2).strip()

        # Determinar si hay alguna transmisión activa
        was_active = ctx.state in (STATE_STREAMING, STATE_CONNECTING, STATE_BT_WAIT, STATE_STARTING)
        
        safe_gui_call(win, lambda: status_var.set("Checking active Bluetooth connections..."))
        connected_devs = get_wsl_connected_devices()
        is_target_connected = any(c_mac.upper() == mac.upper() for _, c_mac in connected_devs)
        
        # 1. Si estaba activo, paramos de forma lógica pero conservando el hardware
        if was_active:
            safe_gui_call(win, lambda: status_var.set("Stopping current audio stream logically..."))
            ctx.stop_event.set()
            # La importación retrasada previene ciclos
            from stream_manager import wait_for_stream_stop
            wait_for_stream_stop(ctx)
            ctx.stop_event.clear()
            
        # 2. Desconectar suavemente otros dispositivos
        other_connected_devs = [c for c in connected_devs if c[1].upper() != mac.upper()]
        if other_connected_devs:
            safe_gui_call(win, lambda: status_var.set("Soft-disconnecting other Bluetooth devices..."))
            for _, c_mac in other_connected_devs:
                run_logged(
                    ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"(echo 'disconnect {c_mac}'; sleep 1) | bluetoothctl"],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
                )
            time.sleep(0.5)

        # 3. Si el objetivo ya está conectado, Warm Restart instantáneo
        if is_target_connected:
            ctx.save_config(mac, name)
            
            run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", 
                 "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl set-sink-volume @DEFAULT_SINK@ 80%"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
            )
            
            safe_gui_call(win, lambda: status_var.set(f"Successful transition to {name}!"))
            safe_gui_call(win, lambda: lbl_current.config(text=f"Current Headphones: {name} ({mac})"))
            from main import show_notification
            show_notification("Bluetooth LDAC", f"Switched to {name} successfully (Warm Restart).")

            ctx.skip_clean_boot = True
            from stream_manager import start_stream_thread
            start_stream_thread(ctx)
            safe_gui_call(win, lambda: status_var.set(f"Connected to {name}. Stream is starting — watch the tray icon."))
            return

        # 4. Si NO está conectado físicamente
        safe_gui_call(win, lambda: status_var.set("Ensuring Bluetooth adapter is attached to WSL..."))
        ensure_bluetooth_active(ctx, lambda msg: safe_gui_call(win, lambda: status_var.set(msg)))

        safe_gui_call(win, lambda: status_var.set("Checking target device status..."))
        paired, trusted, connected = get_device_info(mac)

        if not paired:
            safe_gui_call(win, lambda: status_var.set(f"Pairing with {name} (put it in pairing mode)..."))
            run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"(sleep 1.2; echo 'agent on'; echo 'default-agent'; echo 'scan on'; sleep 5; echo 'pair {mac}'; sleep 8; echo 'scan off') | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=22
            )
            time.sleep(1)

        if not trusted:
            safe_gui_call(win, lambda: status_var.set(f"Configuring trust for {name}..."))
            run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"(sleep 1.2; echo 'agent on'; echo 'default-agent'; echo 'trust {mac}'; sleep 1) | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=8
            )
            time.sleep(0.5)

        safe_gui_call(win, lambda: status_var.set(f"Connecting to {name}..."))
        run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"(sleep 1.2; echo 'agent on'; echo 'default-agent'; echo 'connect {mac}'; sleep 8) | bluetoothctl"],
            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=15
        )
        
        time.sleep(1.0)
        final_paired, final_trusted, final_conn = get_device_info(mac)
        
        # Opción 2: Si está emparejado y es de confianza, pero la conexión física inicial falló (por retardo 
        # en el registro de perfiles de WirePlumber en D-Bus), realizamos un reintento automático silencioso.
        if final_paired and final_trusted and not final_conn:
            safe_gui_call(win, lambda: status_var.set(f"Configuring audio profiles for {name} (3s)..."))
            time.sleep(3.0)
            safe_gui_call(win, lambda: status_var.set(f"Re-connecting to {name} (Auto-Retry)..."))
            run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"(sleep 1.2; echo 'agent on'; echo 'default-agent'; echo 'connect {mac}'; sleep 8) | bluetoothctl"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=15
            )
            time.sleep(1.0)
            final_paired, final_trusted, final_conn = get_device_info(mac)
        
        # Consideramos la fase de configuración exitosa si el dispositivo está emparejado y es de confianza.
        # receptor_audio.sh se encargará de realizar la conexión definitiva y de reiniciar WirePlumber 
        # para evitar el error transitorio 'br-connection-profile-unavailable'.
        if final_paired and final_trusted:
            ctx.save_config(mac, name)
            
            try:
                run_logged(
                    ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", 
                     "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl set-sink-volume @DEFAULT_SINK@ 80%"],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
                )
            except Exception:
                pass
            
            safe_gui_call(win, lambda: status_var.set(f"Successful connection to {name}!"))
            safe_gui_call(win, lambda: lbl_current.config(text=f"Current Headphones: {name} ({mac})"))
            from main import show_notification
            show_notification("Bluetooth LDAC", f"Device {name} configured successfully.")

            ctx.skip_clean_boot = True
            from stream_manager import start_stream_thread
            start_stream_thread(ctx)
            safe_gui_call(win, lambda: status_var.set(f"Connected to {name}. Stream is starting — watch the tray icon."))
        else:
            safe_gui_call(win, lambda: status_var.set("Connection error. Please retry or power on the device."))
            
    except Exception as e:
        safe_gui_call(win, lambda: status_var.set(f"Connection error: {str(e)}"))
    finally:
        safe_gui_call(btn_scan, lambda: btn_scan.config(state="normal"))
        safe_gui_call(btn_connect, lambda: btn_connect.config(state="normal"))
        if btn_disconnect:
            safe_gui_call(btn_disconnect, lambda: btn_disconnect.config(state="normal"))
