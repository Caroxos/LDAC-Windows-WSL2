import sys
import os
import threading
import time
import subprocess
import pystray
from PIL import Image, ImageDraw

from context import AppContext, STATE_STOPPED, STATE_STARTING, STATE_BT_WAIT, STATE_CONNECTING, STATE_STREAMING, STATE_STOPPING, STATE_ERROR
from sys_helpers import (
    CREATE_NO_WINDOW,
    _startupinfo,
    check_single_instance,
    cleanup_pid_file,
    resolve_usbipd_path
)
from logger import log_message, run_logged
from wsl_manager import get_dynamic_busid, USBIPD

# ---- Variables Globales de Lanzamiento ----
ctx = None

def make_icon(color_inner="#00e5ff", color_outer="#1a1a2e", label=""):
    """Genera un icono cuadrado de 64x64 px con un círculo de color."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fondo circular oscuro
    draw.ellipse([2, 2, size - 2, size - 2], fill=color_outer)
    # Círculo interior de color
    draw.ellipse([10, 10, size - 10, size - 10], fill=color_inner)

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

def action_start(icon, item):
    if ctx.state not in (STATE_STOPPED, STATE_ERROR):
        return
    from stream_manager import start_stream_thread
    start_stream_thread(ctx)

def action_stop(icon, item):
    if ctx.state == STATE_STOPPED:
        return
    ctx.stop_event.set()

def action_status(icon, item):
    show_notification("LDAC Status", f"Current status: {ctx.state}")

def action_quit(icon, item):
    """Detiene todo de forma impecable y completa al salir."""
    log_message("User triggered Exit. Shutting down gracefully...")
    ctx.stop_event.set()
    
    from stream_manager import wait_for_stream_stop
    wait_for_stream_stop(ctx)

    # Detach USBIPD
    try:
        run_logged([USBIPD, "detach", "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3)
    except Exception:
        pass

    # Apagar WSL Alpine
    try:
        run_logged(["wsl", "--shutdown"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=4)
    except Exception:
        pass

    cleanup_pid_file()

    try:
        icon.stop()
    except Exception:
        pass

    log_message("Shutdown complete. Exiting process.")
    os._exit(0)

def show_notification(title, message):
    if ctx and ctx.tray_icon:
        ctx.tray_icon.notify(message, title)

def build_menu(is_running=False):
    items = []

    if is_running:
        items.append(pystray.MenuItem("⏹  Stop LDAC", action_stop))
    else:
        items.append(pystray.MenuItem("▶  Start LDAC", action_start, default=True))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(
        "📊  View Statistics",
        lambda icon, item: threading.Thread(
            target=lambda: __import__('gui_monitor').gui_monitor.show_info_window(ctx), daemon=True
        ).start()
    ))
    items.append(pystray.MenuItem(
        "🎧  Configure Bluetooth",
        lambda icon, item: threading.Thread(
            target=lambda: __import__('gui_bt_manager').gui_bt_manager.show_bluetooth_window(ctx), daemon=True
        ).start()
    ))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(f"Status: {ctx.get_state_display()}", action_status, enabled=False))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("✕  Exit", action_quit))

    return pystray.Menu(*items)

# Parchear las lambdas para importar en caliente y evitar ciclos
def show_monitor_window(icon, item):
    from gui_monitor import show_info_window
    threading.Thread(target=show_info_window, args=(ctx,), daemon=True).start()

def show_bt_window(icon, item):
    from gui_bt_manager import show_bluetooth_window
    threading.Thread(target=show_bluetooth_window, args=(ctx,), daemon=True).start()

def build_menu_patched(is_running=False):
    items = []
    if is_running:
        items.append(pystray.MenuItem("⏹  Stop LDAC", action_stop))
    else:
        items.append(pystray.MenuItem("▶  Start LDAC", action_start, default=True))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("📊  View Statistics", show_monitor_window))
    items.append(pystray.MenuItem("🎧  Configure Bluetooth", show_bt_window))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(f"Status: {ctx.get_state_display()}", action_status, enabled=False))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("✕  Exit", action_quit))

    return pystray.Menu(*items)

def rebuild_menu(context_obj):
    if context_obj.tray_icon is None:
        return
    is_running = context_obj.state == STATE_STREAMING
    context_obj.tray_icon.menu = build_menu_patched(is_running)

def sleep_sentinel_loop():
    """Detecta de fondo deriva temporal para auto-resetear WSL/USBIPD tras suspender Windows."""
    last_time = time.time()
    while True:
        time.sleep(1)
        now = time.time()
        delta = now - last_time
        last_time = now
        
        if delta > 10:
            log_message("Windows sleep/suspend detected! Resetting VM and Bluetooth adapter...")
            def run_suspend_reset():
                ctx.state = STATE_STOPPED
                ctx.stop_event.set()
                
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
                
                get_dynamic_busid(ctx)
                try:
                    run_logged([USBIPD, "detach", "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3)
                except Exception:
                    pass
                try:
                    run_logged(["wsl", "--shutdown"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=4)
                except Exception:
                    pass
                
                ctx.stop_event.clear()
                show_notification("LDAC Audio", "System recovered and reset successfully after Windows resume.")
                
            threading.Thread(target=run_suspend_reset, daemon=True).start()

def main():
    global ctx
    check_single_instance()
    
    ctx = AppContext()
    ctx.tray_icon = pystray.Icon(
        name="ldac_audio",
        icon=ICONS[STATE_STOPPED],
        title="LDAC Audio — Stopped",
        menu=build_menu_patched(False),
    )

    log_message("App launched successfully.")

    # Limpieza preventiva en segundo plano (arranque en frío)
    def cold_start_cleanup():
        # Limpiar configuración local en el arranque para evitar perfiles pre-cargados
        try:
            ctx.save_config("", "", "sq")
        except Exception:
            pass
            
        get_dynamic_busid(ctx)
        try:
            run_logged([USBIPD, "detach", "--busid", ctx.BUSID], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3)
        except Exception:
            pass
        try:
            run_logged(["wsl", "--shutdown"], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=4)
        except Exception:
            pass
        # Eliminar físicamente cualquier vinculación Bluetooth antigua en la base de datos de Alpine
        try:
            run_logged(
                ["wsl", "-d", "Alpine", "-u", "root", "rm", "-rf", "/var/lib/bluetooth/*/*"],
                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5
            )
        except Exception:
            pass

    threading.Thread(target=cold_start_cleanup, daemon=True).start()
    
    # Lanzar el hilo centinela de suspensión de Windows
    threading.Thread(target=sleep_sentinel_loop, daemon=True).start()

    ctx.tray_icon.run()

if __name__ == "__main__":
    main()
