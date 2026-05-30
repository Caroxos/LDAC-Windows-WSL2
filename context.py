import os
import re
import json
import threading

STATE_STOPPED    = "Stopped"
STATE_STARTING   = "Starting..."
STATE_BT_WAIT    = "Waiting for Bluetooth..."
STATE_CONNECTING = "Connecting headphones..."
STATE_STREAMING  = "Streaming"
STATE_STOPPING   = "Stopping..."
STATE_ERROR      = "Error"

import sys
if getattr(sys, "frozen", False):
    INSTALL_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(INSTALL_DIR, "ldac_config.json")

class AppContext:
    def __init__(self):
        self._lock = threading.Lock()
        self._config_lock = threading.RLock()
        
        # Estado general
        self._state = STATE_STOPPED
        self.stop_event = threading.Event()
        
        # Subprocesos activos
        self.python_proc = None
        self.wsl_proc = None
        self.bt_anchor_proc = None
        
        # Icono de bandeja
        self.tray_icon = None
        
        # Variables operativas
        self.BUSID = "1-12"
        self.keep_wsl_alive = False
        self.skip_clean_boot = False
        self.active_codec = "?"
        
        # Cargar configuración inicial
        self.load_config()

    @property
    def state(self):
        with self._lock:
            return self._state

    @state.setter
    def state(self, new_state):
        with self._lock:
            self._state = new_state
        
        # Sincronizar con el icono de la bandeja del sistema
        if self.tray_icon:
            from PIL import Image, ImageDraw
            # Importación retrasada para evitar ciclos de importación
            from main import ICONS
            self.tray_icon.icon = ICONS.get(new_state, ICONS[STATE_STOPPED])
            display_state = self.get_state_display()
            self.tray_icon.title = f"LDAC Audio — {display_state}"
            from main import rebuild_menu
            rebuild_menu(self)

    def get_state_display(self):
        with self._lock:
            if self._state == STATE_STREAMING:
                if getattr(self, "active_codec", "?").upper() == "LDAC":
                    return "Streaming LDAC"
                else:
                    return "Streaming Audio"
            return self._state

    def load_config(self):
        default_config = {
            "selected_mac": "",
            "selected_name": "",
            "ldac_mode": "hq"
        }
        if not os.path.exists(CONFIG_FILE):
            self.selected_mac = ""
            self.selected_name = ""
            self.ldac_mode = "hq"
            return default_config
            
        with self._config_lock:
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                    self.selected_mac = cfg.get("selected_mac", "")
                    self.selected_name = cfg.get("selected_name", "")
                    self.ldac_mode = cfg.get("ldac_mode", "hq")
                    return cfg
            except Exception:
                self.selected_mac = ""
                self.selected_name = ""
                self.ldac_mode = "hq"
                return default_config

    def save_config(self, mac, name, ldac_mode=None):
        with self._config_lock:
            try:
                mode = ldac_mode if ldac_mode is not None else self.ldac_mode
                self.selected_mac = mac
                self.selected_name = name
                self.ldac_mode = mode
                
                with open(CONFIG_FILE, "w") as f:
                    json.dump({
                        "selected_mac": mac,
                        "selected_name": name,
                        "ldac_mode": mode
                    }, f, indent=2)
            except Exception:
                pass
