import tkinter as tk
import json
import queue
import time
import threading
from sys_helpers import safe_gui_call, get_safe_stats_file
from stream_manager import _get_ldac_bitrate, _get_pipewire_info

STATS_FILE = get_safe_stats_file()
_info_window = None

def show_info_window(ctx):
    """Abre (o trae al frente) la ventana de monitoreo."""
    global _info_window

    try:
        if _info_window and _info_window.winfo_exists():
            _info_window.lift()
            _info_window.focus_force()
            return
    except Exception:
        _info_window = None

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

    win.title("LDAC Monitor")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    W, H = 360, 310
    win.geometry(f"{W}x{H}+{(win.winfo_screenwidth()-W)//2}+{(win.winfo_screenheight()-H)//2}")

    hdr = tk.Frame(win, bg=ACCENT, height=4)
    hdr.pack(fill="x")

    tk.Label(win, text="LDAC Audio Monitor",
             bg=BG, fg=ACCENT,
             font=("Segoe UI", 13, "bold")).pack(pady=(14, 2))
    tk.Label(win, text="Real-time Statistics",
             bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack()

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
    v_status  = tk.StringVar(master=win, value=ctx.get_state_display())
    
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

    sep = tk.Frame(win, bg=MUTED, height=1)
    sep.pack(fill="x", padx=18)

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

    tk.Button(win, text="Close", command=on_close,
              bg=CARD, fg=MUTED, relief="flat",
              font=("Segoe UI", 8),
              activebackground=ACCENT, activeforeground=BG,
              cursor="hand2").pack(pady=(2, 10))

    _pipewire_cache           = [None, None]
    _pipewire_refresh_counter = [0]
    _ldac_refresh_counter     = [0]
    _ldac_cache               = ["--- kbps", "#888888"]

    def refresh_pipewire():
        d, c = _get_pipewire_info()
        _pipewire_cache[0] = d
        _pipewire_cache[1] = c

    def refresh_ldac_bitrate():
        label, color = _get_ldac_bitrate(ctx)
        _ldac_cache[0] = label
        _ldac_cache[1] = color

    threading.Thread(target=refresh_pipewire,    daemon=True).start()
    threading.Thread(target=refresh_ldac_bitrate, daemon=True).start()

    from context import STATE_STREAMING, STATE_STOPPED
    def update_ui():
        if not win.winfo_exists():
            return
        try:
            v_status.set(ctx.get_state_display())
            dot.config(fg=ACCENT if ctx.state == STATE_STREAMING else
                        YELLOW if ctx.state != STATE_STOPPED else MUTED)

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

            _pipewire_refresh_counter[0] += 1
            if _pipewire_refresh_counter[0] >= 5:
                _pipewire_refresh_counter[0] = 0
                threading.Thread(target=refresh_pipewire, daemon=True).start()

            if _pipewire_cache[0]:
                v_device.set(_pipewire_cache[0])
                v_codec.set(_pipewire_cache[1])

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
