import os
import sys
import re
import time
import json
import threading
import subprocess
from logger import log_message, run_logged, popen_logged, WSL_DISTRO, WSL_USER
from sys_helpers import (
    CREATE_NO_WINDOW,
    _startupinfo,
    resolve_usbipd_path,
    register_process_in_job,
    get_safe_stats_file
)
from wsl_manager import ensure_usbipd_service, ensure_device_bound, ensure_bluetooth_active

INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
EMISOR_PY = os.path.join(INSTALL_DIR, "emisor_audio.py")
USBIPD = resolve_usbipd_path()
STATS_FILE = get_safe_stats_file()

_start_thread = None

def start_stream_thread(ctx):
    """Lanza el hilo de la transmisión de audio."""
    global _start_thread
    _start_thread = threading.Thread(target=start_ldac, args=(ctx,), daemon=True)
    _start_thread.start()

def wait_for_stream_stop(ctx):
    """Espera síncronamente a que el hilo de transmisión se detenga."""
    global _start_thread
    if _start_thread and _start_thread.is_alive():
        _start_thread.join(timeout=5)
        
        # Forzar parada de procesos residuales si sigue colgado
        try:
            if ctx.python_proc and ctx.python_proc.poll() is None:
                ctx.python_proc.kill()
        except Exception:
            pass
        ctx.python_proc = None
        
        try:
            if ctx.wsl_proc and ctx.wsl_proc.poll() is None:
                ctx.wsl_proc.kill()
        except Exception:
            pass
        ctx.wsl_proc = None

def start_ldac(ctx):
    """Lógica principal de inicio de la transmisión LDAC."""
    from context import (
        STATE_STOPPED, STATE_STARTING, STATE_BT_WAIT,
        STATE_CONNECTING, STATE_STREAMING, STATE_ERROR
    )
    from main import show_notification

    selected_mac = ctx.selected_mac
    if not selected_mac:
        ctx.state = STATE_STOPPED
        return

    ctx.stop_event.clear()

    try:
        ensure_usbipd_service()
        
        # 0. Limpieza previa
        ctx.state = STATE_STARTING
        if not ctx.skip_clean_boot:
            run_logged([USBIPD, "detach", "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5)
            run_logged(["wsl", "--shutdown"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5)
            time.sleep(1)

            # 1. Bind USBIPD
            ensure_device_bound(ctx)

            # 2. Pre-cargar modulos
            run_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "modprobe", "vhci-hcd"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
            run_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "modprobe", "btusb"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
            
            # Copiar receptor_audio.sh a Alpine
            receptor_local = os.path.join(INSTALL_DIR, "receptor_audio.sh")
            if os.path.exists(receptor_local):
                try:
                    with open(receptor_local, "r", encoding="utf-8") as rf:
                        content = rf.read()
                    proc = subprocess.Popen(
                        ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", "cat > /root/receptor_audio.sh"],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
                    )
                    proc.communicate(input=content.encode("utf-8"), timeout=5)
                except Exception:
                    pass
            run_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "chmod", "+x", "/root/receptor_audio.sh"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10)
            time.sleep(1)

            # Mantener viva la distribución
            boot_proc = popen_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sleep", "10"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo())
            time.sleep(1)

            # 3. Attach USBIPD
            run_logged([USBIPD, "attach", "--wsl", WSL_DISTRO, "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=20)

            try:
                boot_proc.terminate()
            except Exception:
                pass
        else:
            ctx.skip_clean_boot = False
            # Si el adaptador hci0 ya está activo, evitamos re-inicializar
            # los servicios de WSL para no interrumpir conexiones Bluetooth activas.
            hci0_ok = False
            try:
                res = run_logged(
                    ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "test", "-d", "/sys/class/bluetooth/hci0"],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
                )
                if res.returncode == 0:
                    hci0_ok = True
            except Exception:
                pass
            
            if not hci0_ok:
                ensure_bluetooth_active(ctx)

        # 4. Iniciar receptor de audio en Alpine
        ctx.state = STATE_BT_WAIT
        ldac_mode = ctx.ldac_mode

        err_file = subprocess.DEVNULL
        err_log_path = os.path.join(INSTALL_DIR, "err.log")
        try:
            err_file = open(err_log_path, "w", encoding="utf-8")
        except Exception:
            err_file = subprocess.DEVNULL

        ctx.wsl_proc = popen_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "ash", "-c",
             f"/root/receptor_audio.sh {selected_mac} {ldac_mode}"],
            stdout=subprocess.DEVNULL,
            stderr=err_file,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )
        register_process_in_job(ctx.wsl_proc)

        # 5. Esperar hci0
        ctx.state = STATE_CONNECTING
        for _ in range(15):
            if ctx.stop_event.is_set():
                return
            result = run_logged(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "test", "-d", "/sys/class/bluetooth/hci0"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
            )
            if result.returncode == 0:
                break
            time.sleep(1)

        # 6. Iniciar el emisor Python
        if getattr(sys, "frozen", False):
            ctx.python_proc = popen_logged(
                [sys.executable, "--emisor"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=_startupinfo(),
            )
        else:
            ctx.python_proc = popen_logged(
                [sys.executable, EMISOR_PY],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=_startupinfo(),
            )
        register_process_in_job(ctx.python_proc)

        # 7. Esperar a que PipeWire detecte el sink
        bluez_found = False
        for _ in range(15):
            if ctx.stop_event.is_set():
                return
            try:
                check = run_logged(
                    ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c",
                      "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl list sinks short 2>/dev/null"],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
                )
                stdout_str = check.stdout.decode("utf-8", errors="replace")
                if "bluez" in stdout_str:
                    bluez_found = True
                    break
            except Exception as e:
                log_message(f"pactl list sinks failed (normal during PipeWire restart): {str(e)}")
            time.sleep(2)

        if bluez_found:
            ctx.state = STATE_STREAMING
        else:
            ctx.state = STATE_ERROR
            show_notification("LDAC", "No Bluetooth device connected. Open Configure Bluetooth to pair your headphones.")
            return

        # Mantener monitoreo
        while not ctx.stop_event.is_set():
            if ctx.wsl_proc and ctx.wsl_proc.poll() is not None:
                break
            if ctx.python_proc and ctx.python_proc.poll() is not None:
                break
            try:
                _, codec = _get_pipewire_info()
                ctx.active_codec = codec
            except Exception:
                pass
            time.sleep(2)

    except Exception as e:
        ctx.state = STATE_ERROR
        show_notification("LDAC Error", str(e))
    finally:
        if 'err_file' in locals() and err_file not in (None, subprocess.DEVNULL):
            try:
                err_file.close()
            except Exception:
                pass
                
        if not ctx.stop_event.is_set():
            err_msg = ""
            err_log_path = os.path.join(INSTALL_DIR, "err.log")
            if os.path.exists(err_log_path):
                try:
                    with open(err_log_path, "r", encoding="utf-8") as f:
                        err_content = f.read()
                    if "Address already in use" in err_content or "bind:" in err_content:
                        err_msg = "UDP Port Conflict: Port 5005 is already in use inside " + WSL_DISTRO + "."
                    elif "audio server could not be started" in err_content:
                        err_msg = "Audio Server Error: PipeWire audio server failed to start inside " + WSL_DISTRO + "."
                    elif "Bluetooth adapter hci0 did not appear" in err_content:
                        err_msg = "Bluetooth Adapter Error: Bluetooth controller (hci0) did not initialize in time."
                except Exception:
                    pass
            
            if err_msg:
                ctx.state = STATE_ERROR
                show_notification("LDAC Error", err_msg)
            elif ctx.wsl_proc and ctx.wsl_proc.poll() is not None and ctx.wsl_proc.poll() != 0:
                ctx.state = STATE_ERROR
                show_notification("LDAC Error", "Receptor process exited unexpectedly. Verify Bluetooth/WSL services.")
                
        stop_ldac_cleanup(ctx)

def stop_ldac_cleanup(ctx):
    """Limpieza de todos los recursos al detener la transmisión."""
    from context import STATE_STOPPING, STATE_STOPPED
    
    ctx.state = STATE_STOPPING

    # Matar emisor Python
    if ctx.python_proc and ctx.python_proc.poll() is None:
        try:
            ctx.python_proc.terminate()
        except Exception:
            pass
        try:
            ctx.python_proc.wait(timeout=3)
        except Exception:
            try:
                ctx.python_proc.kill()
            except Exception:
                pass
    ctx.python_proc = None

    # Matar receptor WSL
    if ctx.wsl_proc and ctx.wsl_proc.poll() is None:
        try:
            ctx.wsl_proc.terminate()
        except Exception:
            pass
    ctx.wsl_proc = None

    if not ctx.keep_wsl_alive:
        run_logged([USBIPD, "detach", "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5)
        run_logged(["wsl", "--shutdown"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5)
    else:
        run_logged(["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "killall", "-9", "nc", "pacat"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5)

    ctx.active_codec = "?"
    ctx.state = STATE_STOPPED

def _get_ldac_bitrate(ctx):
    """Consulta el bitrate LDAC real de PipeWire o de la configuración local."""
    try:
        res = run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c",
             "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl list sinks 2>/dev/null"],
            timeout=4, creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
        )
        out = res.stdout.decode("utf-8", errors="replace")
        
        is_ldac = "ldac" in out.lower()
        if is_ldac:
            m_qual = re.search(r'bluez5\.a2dp\.ldac\.quality\s*=\s*"([^"]+)"', out)
            quality = m_qual.group(1) if m_qual else None
            
            if not quality:
                quality = ctx.ldac_mode
                
            if quality == "hq":
                return "990 kbps", "#00ff88"
            elif quality == "sq":
                return "660 kbps", "#f0c040"
            elif quality == "mq":
                return "330 kbps", "#ff6644"
            elif quality == "auto":
                return "Adaptive (Auto)", "#00e5ff"
    except Exception as e:
        log_message(f"get_ldac_bitrate error: {str(e)}")
    return "?", "#888888"

def _get_pipewire_info():
    """Consulta pactl en Alpine y devuelve (device_name, codec)."""
    try:
        res = run_logged(
            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c",
             "PULSE_SERVER=unix:/tmp/runtime-root/pulse/native pactl list sinks 2>/dev/null"],
            timeout=4, creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo()
        )
        out = res.stdout.decode("utf-8", errors="replace")

        name_m  = re.search(r'device\.description = "([^"]+)"', out)
        codec_m = re.search(r'api\.bluez5\.codec = "([^"]+)"', out)

        device  = name_m.group(1) if name_m else "Unknown"
        codec   = codec_m.group(1).upper() if codec_m else "?"
        return device, codec
    except Exception as e:
        log_message(f"get_pipewire_info error: {str(e)}")
        return "No connection", "?"
