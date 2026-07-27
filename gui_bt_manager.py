import sys
import tkinter as tk
from tkinter import messagebox

# Force UTF-8 output to prevent UnicodeEncodeError on non-Latin Windows locales (e.g. cp950)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import queue
import re
import subprocess
import threading
from logger import log_message, run_logged, WSL_DISTRO, WSL_USER
from sys_helpers import CREATE_NO_WINDOW, _startupinfo, safe_gui_call
from wsl_manager import ensure_bluetooth_active, get_dynamic_busid, USBIPD
from bt_scanner import (
    get_wsl_paired_devices,
    get_discovered_devices,
    get_wsl_connected_devices,
    run_scan_bg,
    run_connect_bg
)

_bt_window = None

def show_bluetooth_window(ctx):
    """Abre la ventana de configuración de Bluetooth."""
    global _bt_window
    ctx.keep_wsl_alive = True
    
    try:
        if _bt_window and _bt_window.winfo_exists():
            _bt_window.lift()
            _bt_window.focus_force()
            return
    except Exception:
        _bt_window = None

    # Iniciar el proceso ancla de WSL para evitar que la VM se aduerma
    try:
        if not ctx.bt_anchor_proc or ctx.bt_anchor_proc.poll() is not None:
            log_message("Launching Window Lifecycle Keep-Alive Anchor...")
            ctx.bt_anchor_proc = subprocess.Popen(
                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sleep", "infinity"],
                creationflags=CREATE_NO_WINDOW,
                startupinfo=_startupinfo()
            )
    except Exception as e:
        log_message(f"Error starting anchor process: {str(e)}")
        ctx.bt_anchor_proc = None

    BG        = "#0d0d1a"
    CARD      = "#161628"
    ACCENT    = "#00e5ff"
    TEXT      = "#e8e8f0"
    MUTED     = "#6868a0"
    GREEN     = "#00ff88"
    YELLOW    = "#f0c040"

    win = tk.Tk()
    win.gui_queue = queue.Queue()
    
    def process_queue():
        while not win.gui_queue.empty():
            try:
                callback = win.gui_queue.get_nowait()
                callback()
            except queue.Empty:
                break
        try:
            if win.winfo_exists():
                win.after(100, process_queue)
        except Exception:
            pass

    win.after(100, process_queue)

    win.title("Bluetooth Device Manager")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    W, H = 400, 570
    win.geometry(f"{W}x{H}+{(win.winfo_screenwidth()-W)//2}+{(win.winfo_screenheight()-H)//2}")

    hdr = tk.Frame(win, bg=ACCENT, height=4)
    hdr.pack(fill="x")

    tk.Label(win, text="Configure Bluetooth Device",
             bg=BG, fg=ACCENT,
             font=("Segoe UI", 12, "bold")).pack(pady=(12, 2))
    
    from context import STATE_STREAMING
    if ctx.state == STATE_STREAMING and ctx.selected_mac:
        disp_text = f"Current Headphones: {ctx.selected_name} ({ctx.selected_mac})"
        initial_color = GREEN
    else:
        disp_text = "Current Headphones: None Connected"
        initial_color = MUTED
        
    lbl_current = tk.Label(win, text=disp_text,
                           bg=BG, fg=initial_color, font=("Segoe UI", 9, "italic"),
                           wraplength=360, justify="center")
    lbl_current.pack(pady=(0, 6))

    _scan_active = [False]
    _connect_active = [False]

    def check_active_connection():
        if _scan_active[0] or _connect_active[0]:
            return
        try:
            connected_devs = get_wsl_connected_devices()
            
            # Fallback en caso de que D-Bus esté lento/congestionado durante el streaming activo
            from context import STATE_STREAMING
            if not connected_devs and ctx.state == STATE_STREAMING and ctx.selected_mac:
                connected_devs = [(ctx.selected_name, ctx.selected_mac)]
                
            if connected_devs:
                devs_strs = [f"{name} ({mac})" for name, mac in connected_devs]
                disp_text = f"Connected: {' & '.join(devs_strs)}"
                value_color = GREEN
                
                # [AUTO-HEAL] Si detectamos un dispositivo conectado pero no hay configuración activa, auto-vinculamos
                if not ctx.selected_mac:
                    name, mac = connected_devs[0]
                    log_message(f"[AUTO-HEAL] Connected device detected: {name} ({mac}). Syncing configuration and starting stream thread...")
                    ctx.save_config(mac, name, ctx.ldac_mode)
                    
                    # Actualizar estado de UI
                    safe_gui_call(win, lambda: v_status.set(f"Auto-healed connection: {name}. Starting stream..."))
                    
                    # Lanzar transmisión omitiendo limpieza invasiva
                    ctx.skip_clean_boot = True
                    from stream_manager import start_stream_thread
                    start_stream_thread(ctx)
                
                # Check active codec to see if we should block LDAC quality settings
                from stream_manager import _get_pipewire_info
                _, codec = _get_pipewire_info()
                
                # Save in context for generic state messages
                ctx.active_codec = codec
                
                def update_quality_widgets():
                    if codec and codec != "?" and codec.upper() != "LDAC" and codec.upper() != "NO CONNECTION":
                        # Connected but NOT using LDAC
                        win.r_hq.config(state="disabled")
                        win.r_sq.config(state="disabled")
                        win.r_auto.config(state="disabled")
                        win.lbl_quality.config(text="LDAC Audio Quality (Disabled for SBC/AAC):", fg=MUTED)
                    else:
                        # Either not connected, or connected using LDAC
                        win.r_hq.config(state="normal")
                        win.r_sq.config(state="normal")
                        win.r_auto.config(state="normal")
                        win.lbl_quality.config(text="LDAC Audio Quality:", fg=TEXT)
                        
                safe_gui_call(win, update_quality_widgets)
            else:
                disp_text = "Current Headphones: None Connected"
                value_color = MUTED
                ctx.active_codec = "?"
                
                # Not connected, enable quality settings
                def restore_quality_widgets():
                    win.r_hq.config(state="normal")
                    win.r_sq.config(state="normal")
                    win.r_auto.config(state="normal")
                    win.lbl_quality.config(text="LDAC Audio Quality:", fg=TEXT)
                safe_gui_call(win, restore_quality_widgets)
                
            safe_gui_call(win, lambda: lbl_current.config(text=disp_text, fg=value_color))
        except Exception:
            pass

    def connection_poller():
        try:
            if win.winfo_exists():
                threading.Thread(target=check_active_connection, daemon=True).start()
                win.after(2000, connection_poller)
        except Exception:
            pass

    win.after(500, connection_poller)
    _btn_refs = {"disconnect": None}

    def on_clear_devices():
        if not messagebox.askyesno("Confirm", "Are you sure you want to clear and unpair all saved Bluetooth devices?", parent=win):
            return
        
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        if _btn_refs["disconnect"]:
            _btn_refs["disconnect"].config(state="disabled")
        btn_clear.config(state="disabled")
        v_status.set("Cleaning device cache...")
        
        def run_clear_bg():
            try:
                # 1. Obtener la lista de dispositivos emparejados de forma directa y offline (sin D-Bus)
                paired_devs = get_wsl_paired_devices()
                macs = [mac for _, mac in paired_devs]
                
                if macs:
                    for target_mac in macs:
                        safe_gui_call(win, lambda t_mac=target_mac: v_status.set(f"Removing {t_mac}..."))
                        
                        # A. Intentar remoción vía bluetoothctl con timeout corto (por si dbus responde)
                        try:
                            run_logged(
                                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "bluetoothctl", "remove", target_mac],
                                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
                            )
                        except Exception:
                            pass
                            
                        # B. Eliminar físicamente los archivos de vinculación en Alpine (garantiza la limpieza)
                        try:
                            run_logged(
                                ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "rm", "-rf", f"/var/lib/bluetooth/*/{target_mac}"],
                                creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
                            )
                        except Exception:
                            pass
                    
                    # C. Reiniciar suavemente bluetoothd para limpiar su caché interno si estuviera cargado
                    try:
                        run_logged(
                            ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "killall", "-9", "bluetoothd"],
                            creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3
                        )
                    except Exception:
                        pass
                
                # 2. Limpiar la configuración local de la aplicación
                ctx.save_config("", "", "sq")
                
                def update_clear_ui():
                    listbox.delete(0, tk.END)
                    lbl_current.config(text="Current Headphones: None Configured", fg=MUTED)
                    v_status.set("Device cache cleared successfully!")
                safe_gui_call(win, update_clear_ui)
            except Exception as e:
                safe_gui_call(win, lambda: v_status.set(f"Error clearing: {str(e)}"))
            finally:
                safe_gui_call(btn_scan, lambda: btn_scan.config(state="normal"))
                safe_gui_call(btn_connect, lambda: btn_connect.config(state="normal"))
                if _btn_refs["disconnect"]:
                    safe_gui_call(_btn_refs["disconnect"], lambda: _btn_refs["disconnect"].config(state="normal"))
                safe_gui_call(btn_clear, lambda: btn_clear.config(state="normal"))
                
        threading.Thread(target=run_clear_bg, daemon=True).start()

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
        unique_devs = {}
        wsl_devs = get_wsl_paired_devices()
        for name, mac in wsl_devs:
            unique_devs[mac] = name
            
        known = get_discovered_devices()
        for name, mac in known:
            unique_devs[mac] = name
            
        for mac, name in sorted(unique_devs.items(), key=lambda x: x[1] if x[1] else x[0]):
            disp_name = name if name else "Unknown Device"
            listbox.insert(tk.END, f"{disp_name} ({mac})")
    except Exception:
        pass

    frame_quality = tk.Frame(win, bg=CARD, bd=1, relief="flat", padx=10, pady=8)
    frame_quality.pack(fill="x", padx=18, pady=5)
    
    lbl_quality = tk.Label(frame_quality, text="LDAC Audio Quality:", bg=CARD, fg=TEXT, font=("Segoe UI", 9, "bold"))
    lbl_quality.pack(anchor="w", pady=(0, 5))
    
    v_mode = tk.StringVar(master=win, value=ctx.ldac_mode)
    win.v_mode = v_mode
    
    def on_mode_change():
        ctx.save_config(ctx.selected_mac, ctx.selected_name, v_mode.get())
        v_status.set(f"Mode saved: {v_mode.get().upper()}. Restart the app to apply.")
    
    r_hq = tk.Radiobutton(frame_quality, text="Extreme Quality (990 kbps)", variable=v_mode, value="hq",
                          bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=ACCENT,
                          selectcolor=CARD, font=("Segoe UI", 9), command=on_mode_change, cursor="hand2")
    r_hq.pack(anchor="w", pady=2)
    
    r_sq = tk.Radiobutton(frame_quality, text="Stable Mode (660 kbps)", variable=v_mode, value="sq",
                          bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=ACCENT,
                          selectcolor=CARD, font=("Segoe UI", 9), command=on_mode_change, cursor="hand2")
    r_sq.pack(anchor="w", pady=2)
    
    r_auto = tk.Radiobutton(frame_quality, text="Adaptive Mode (Auto)", variable=v_mode, value="auto",
                            bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=ACCENT,
                            selectcolor=CARD, font=("Segoe UI", 9), command=on_mode_change, cursor="hand2")
    r_auto.pack(anchor="w", pady=2)

    win.lbl_quality = lbl_quality
    win.r_hq = r_hq
    win.r_sq = r_sq
    win.r_auto = r_auto

    v_status = tk.StringVar(master=win, value="Ready.")
    win.v_status = v_status
    status_bar = tk.Label(win, textvariable=v_status, bg=BG, fg=YELLOW,
                          font=("Segoe UI", 9), wraplength=360, justify="center")
    status_bar.pack(pady=5, padx=18)

    def on_scan():
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        btn_disconnect.config(state="disabled")
        _scan_active[0] = True
        def wrapped_scan():
            try:
                run_scan_bg(ctx, v_status, listbox, btn_scan, btn_connect, btn_disconnect)
            finally:
                _scan_active[0] = False
        threading.Thread(target=wrapped_scan, daemon=True).start()

    def on_connect():
        sel = listbox.curselection()
        if not sel:
            v_status.set("Please select a device from the list.")
            return
        selected_str = listbox.get(sel[0])
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        btn_disconnect.config(state="disabled")
        
        _connect_active[0] = True
        def wrapped_connect():
            try:
                run_connect_bg(ctx, selected_str, v_status, btn_scan, btn_connect, win, lbl_current, btn_disconnect)
            finally:
                _connect_active[0] = False
        threading.Thread(target=wrapped_connect, daemon=True).start()

    def on_disconnect():
        mac = ctx.selected_mac
        name = ctx.selected_name
        if not mac:
            v_status.set("No device is currently configured.")
            return
            
        btn_scan.config(state="disabled")
        btn_connect.config(state="disabled")
        btn_disconnect.config(state="disabled")
        v_status.set(f"Disconnecting {name}...")
        
        def run_disconnect_bg():
            try:
                ctx.keep_wsl_alive = True
                ctx.stop_event.set()
                from stream_manager import wait_for_stream_stop
                wait_for_stream_stop(ctx)
                ctx.stop_event.clear()
                ctx.keep_wsl_alive = False
                
                run_logged(
                    ["wsl", "-d", WSL_DISTRO, "-u", WSL_USER, "sh", "-c", f"(echo 'agent on'; echo 'default-agent'; echo 'disconnect {mac}'; sleep 3) | bluetoothctl"],
                    creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=10
                )
                
                ctx.save_config("", "", "sq")
                
                def update_disconnect_ui():
                    lbl_current.config(text="Current Headphones: None Configured")
                    v_status.set(f"Disconnected from {name} and cleared configuration successfully.")
                safe_gui_call(win, update_disconnect_ui)
                from main import show_notification
                show_notification("Bluetooth LDAC", f"Device {name} disconnected.")
            except Exception as e:
                safe_gui_call(win, lambda: v_status.set(f"Error disconnecting: {str(e)}"))
            finally:
                safe_gui_call(btn_scan, lambda: btn_scan.config(state="normal"))
                safe_gui_call(btn_connect, lambda: btn_connect.config(state="normal"))
                safe_gui_call(btn_disconnect, lambda: btn_disconnect.config(state="normal"))
                
        threading.Thread(target=run_disconnect_bg, daemon=True).start()

    btn_frame1 = tk.Frame(win, bg=BG)
    btn_frame1.pack(fill="x", padx=18, pady=(5, 2))
    
    btn_scan = tk.Button(btn_frame1, text="🔍 Scan Devices", command=on_scan,
                         bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                         relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=10, pady=4)
    btn_scan.pack(side="left", fill="x", expand=True, padx=(0, 4))

    btn_connect = tk.Button(btn_frame1, text="🔗 Connect", command=on_connect,
                             bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                             relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=10, pady=4)
    btn_connect.pack(side="left", fill="x", expand=True, padx=(4, 0))

    btn_frame2 = tk.Frame(win, bg=BG)
    btn_frame2.pack(fill="x", padx=18, pady=(2, 12))
    
    btn_disconnect = tk.Button(btn_frame2, text="🔌 Disconnect", command=on_disconnect,
                               bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                               relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=10, pady=4)
    btn_disconnect.pack(side="left", fill="x", expand=True, padx=(0, 4))
    _btn_refs["disconnect"] = btn_disconnect

    def on_close():
        global _bt_window
        _bt_window = None
        ctx.keep_wsl_alive = False
        
        # Terminar proceso ancla de VM
        if ctx.bt_anchor_proc:
            log_message("Terminating Window Lifecycle VM Anchor...")
            try:
                ctx.bt_anchor_proc.terminate()
            except Exception:
                pass
            ctx.bt_anchor_proc = None
        
        from context import STATE_STREAMING, STATE_CONNECTING, STATE_BT_WAIT, STATE_STARTING
        if ctx.state not in (STATE_STREAMING, STATE_CONNECTING, STATE_BT_WAIT, STATE_STARTING):
            def run_close_cleanup():
                get_dynamic_busid(ctx)
                try:
                    run_logged([USBIPD, "detach", "--busid", ctx.BUSID],
                               creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3)
                except Exception:
                    pass
                try:
                    run_logged(["wsl", "--shutdown"],
                               creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=4)
                except Exception:
                    pass
            threading.Thread(target=run_close_cleanup, daemon=True).start()
            
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    btn_close = tk.Button(btn_frame2, text="✕ Close", command=on_close,
                          bg=CARD, fg=MUTED, activebackground="#ff4444", activeforeground=TEXT,
                          relief="flat", font=("Segoe UI", 9), cursor="hand2", padx=10, pady=4)
    btn_close.pack(side="left", fill="x", expand=True, padx=(4, 0))

    _bt_window = win
    win.mainloop()
