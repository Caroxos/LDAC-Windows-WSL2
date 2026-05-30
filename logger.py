import os
import time
import subprocess
import threading
import json
from datetime import datetime

# Directorio local de logs
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(INSTALL_DIR, "logs")
SESSION_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOGS_DIR, f"ldac_session_{SESSION_TIMESTAMP}.log")
DEBUG_FILE = os.path.join(LOGS_DIR, "last_scan_debug.json")

_log_lock = threading.Lock()

def clean_old_logs():
    """Mantiene un máximo de 10 archivos de log de sesión para evitar saturar el disco."""
    try:
        if not os.path.exists(LOGS_DIR):
            return
        files = [
            os.path.join(LOGS_DIR, f)
            for f in os.listdir(LOGS_DIR)
            if f.startswith("ldac_session_") and f.endswith(".log")
        ]
        files.sort()
        while len(files) > 10:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
            except Exception:
                pass
    except Exception:
        pass

def ensure_logs_dir():
    """Garantiza la existencia de la carpeta de logs y limpia archivos antiguos."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        clean_old_logs()
    except Exception:
        pass

def log_message(msg):
    """Escribe un mensaje de diagnóstico con timestamp en el log unificado."""
    ensure_logs_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    with _log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {msg}\n")
        except Exception:
            pass

def log_scan_results(devices):
    """Vuelca de forma estructurada en un archivo JSON los resultados del último escaneo."""
    ensure_logs_dir()
    try:
        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "devices_found_count": len(devices),
            "devices": [{"name": d[0], "mac": d[1]} for d in devices]
        }
        with _log_lock:
            with open(DEBUG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def run_logged(cmd, **kwargs):
    """
    Ejecuta un comando síncrono (subprocess.run) y registra detalladamente
    los argumentos, duración, return code, stdout y stderr.
    """
    ensure_logs_dir()
    cmd_str = " ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd)
    log_message(f"EXEC: {cmd_str}")
    
    start_time = time.time()
    try:
        # Forzar captura si no está especificado para poder auditar salidas
        capture_out = kwargs.pop("capture_output", True)
        
        res = subprocess.run(
            cmd,
            capture_output=capture_out,
            **kwargs
        )
        duration = (time.time() - start_time) * 1000 # Duración en milisegundos
        
        stdout_str = res.stdout.decode("utf-8", errors="replace").strip() if res.stdout else ""
        stderr_str = res.stderr.decode("utf-8", errors="replace").strip() if res.stderr else ""
        
        log_message(f"DONE ({duration:.1f}ms) | Code: {res.returncode}")
        if stdout_str:
            log_message(f"  STDOUT: {stdout_str}")
        if stderr_str:
            log_message(f"  STDERR: {stderr_str}")
            
        return res
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        log_message(f"FAIL ({duration:.1f}ms) | Error: {str(e)}")
        raise e

def popen_logged(cmd, **kwargs):
    """
    Inicia un comando en segundo plano (subprocess.Popen) y registra
    el inicio del proceso y sus argumentos.
    """
    ensure_logs_dir()
    cmd_str = " ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd)
    log_message(f"LAUNCH BG: {cmd_str}")
    
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        log_message(f"BG STARTED | PID: {proc.pid}")
        return proc
    except Exception as e:
        log_message(f"BG LAUNCH FAILED | Error: {str(e)}")
        raise e
