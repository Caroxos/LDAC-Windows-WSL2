import sys
import os
import ctypes
import shutil
import tempfile
import re
import time
import tkinter as tk
import subprocess
from logger import log_message

CREATE_NO_WINDOW = 0x08000000
import sys
if getattr(sys, "frozen", False):
    INSTALL_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))

def _startupinfo():
    """STARTUPINFO con ventana oculta para subprocesos de Windows."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def show_native_message_box(title, message, is_error=True):
    """Muestra un diálogo de diálogo nativo de Windows (thread-safe)."""
    try:
        style = 0x10 if is_error else 0x40 # MB_ICONERROR o MB_ICONINFORMATION
        # MB_TASKMODAL (0x2000) + MB_SETFOREGROUND (0x10000)
        ctypes.windll.user32.MessageBoxW(0, message, title, style | 0x2000 | 0x10000)
    except Exception:
        pass

# ---- Configuración de Job Objects (Prevención de procesos huérfanos) ----
h_job = None
try:
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    h_job = kernel32.CreateJobObjectW(None, None)
    if h_job:
        # Layout real de Windows: LimitFlags va después de los dos LARGE_INTEGER de tiempo.
        # (Antes estaba en el offset 0, así que KILL_ON_JOB_CLOSE nunca quedaba activo y los
        # procesos --emisor sobrevivían al cerrar la app.)
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wintypes.DWORD),
                ('SchedulingClass', wintypes.DWORD),
            ]
        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t),
            ]
        
        limit = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit.BasicLimitInformation.LimitFlags = 0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        
        if not kernel32.SetInformationJobObject(
            h_job, 9, # JobObjectExtendedLimitInformation
            ctypes.byref(limit),
            ctypes.sizeof(limit)
        ):
            log_message(f"SetInformationJobObject failed (error {kernel32.GetLastError()})")
            h_job = None
except Exception:
    h_job = None

def register_process_in_job(proc):
    """Registra un subproceso Popen en el Job Object para auto-liquidación automática."""
    global h_job
    if h_job and proc:
        handle = getattr(proc, "_handle", None)
        if handle:
            try:
                ctypes.windll.kernel32.AssignProcessToJobObject(h_job, int(handle))
            except Exception:
                pass

def resolve_usbipd_path():
    """Busca usbipd en PATH y rutas conocidas. Devuelve la primera que exista."""
    from logger import log_message, USBIPD_OVERRIDE_PATH
    if USBIPD_OVERRIDE_PATH and os.path.exists(USBIPD_OVERRIDE_PATH):
        return USBIPD_OVERRIDE_PATH
    path_in_path = shutil.which("usbipd")
    if path_in_path:
        return path_in_path
    candidates = [
        r"C:\Program Files\usbipd-win\usbipd.exe",
    ]
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Microsoft", "WinGet", "Links", "usbipd.exe"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

def is_pid_running(pid):
    """Verifica si un PID está activo y valida de forma nativa que sea de Python/LDAC."""
    try:
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if handle:
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.psapi.GetModuleBaseNameW(handle, None, buf, ctypes.sizeof(buf)//2)
            proc_name = buf.value.lower()
            
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            
            if exit_code.value == 259: # STILL_ACTIVE
                return any(kw in proc_name for kw in ["python", "ldac_tray"])
        else:
            err = ctypes.windll.kernel32.GetLastError()
            if err == 5: # Acceso Denegado: existe pero tiene privilegios elevados
                return False
        return False
    except Exception:
        try:
            res = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True)
            stdout_str = res.stdout.decode("utf-8", errors="replace").lower()
            return str(pid) in stdout_str and any(kw in stdout_str for kw in ["python", "ldac_tray"])
        except Exception:
            return False

def kill_process_tree(proc):
    """Termina un subproceso y todos sus descendientes.

    En el ejecutable empaquetado (PyInstaller onefile) cada `LDAC_Audio.exe --emisor` es un
    cargador que lanza un segundo proceso con el Python real: terminate() solo mata al
    cargador y el emisor que captura el audio quedaba vivo.
    """
    if not proc or proc.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW,
                       startupinfo=_startupinfo(), timeout=5)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass

def kill_stale_emitters():
    """Mata emisores (--emisor) que hayan quedado de sesiones anteriores.

    Varios emisores capturando el mismo loopback se pisan entre sí y no llega audio.
    """
    own = os.getpid()
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne " + str(own) + " -and ("
        "($_.Name -like 'LDAC_Audio*' -and $_.CommandLine -match '--emisor') -or "
        "$_.CommandLine -match 'emisor_audio\\.py') } | ForEach-Object { $_.ProcessId }"
    )
    try:
        res = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                             capture_output=True, creationflags=CREATE_NO_WINDOW,
                             startupinfo=_startupinfo(), timeout=15)
        pids = [int(p) for p in res.stdout.decode("utf-8", errors="replace").split() if p.isdigit()]
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=5)
        if pids:
            log_message(f"Killed {len(pids)} stale emitter process(es): {pids}")
    except Exception as e:
        log_message(f"kill_stale_emitters error: {e}")

def kill_pid(pid):
    """Termina de forma forzada un proceso por su PID."""
    try:
        os.kill(pid, 9)
        time.sleep(0.5)
    except Exception:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], creationflags=CREATE_NO_WINDOW, startupinfo=_startupinfo(), timeout=3)
        except Exception:
            pass

_mutex_holder = None # Guard para mantener viva la referencia del Mutex del kernel de Windows

def check_single_instance():
    """Garantiza de forma atómica y a nivel de Kernel que solo haya una instancia de la aplicación."""
    global _mutex_holder
    script_name = os.path.basename(sys.argv[0]).replace(".py", "")
    
    # 1. Chequeo atómico con Named Mutex en Windows para erradicar iconos fantasmas en el arranque
    try:
        mutex_name = f"Global\\LdacAudioMutex_{script_name}"
        h_mutex = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
        err = ctypes.windll.kernel32.GetLastError()
        if err == 183: # ERROR_ALREADY_EXISTS
            if h_mutex:
                ctypes.windll.kernel32.CloseHandle(h_mutex)
            sys.exit(0)
        _mutex_holder = h_mutex
    except Exception:
        pass

    # 2. Mantener el archivo PID tradicional para compatibilidad de diagnóstico y tareas de kill
    pid_file = os.path.join(tempfile.gettempdir(), f"ldac_audio_{script_name}.pid")
    try:
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

def cleanup_pid_file():
    """Elimina el archivo PID de la instancia actual al salir."""
    try:
        script_name = os.path.basename(sys.argv[0]).replace(".py", "")
        pid_file = os.path.join(tempfile.gettempdir(), f"ldac_audio_{script_name}.pid")
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass

def safe_gui_call(widget, callback):
    """Ejecuta un callback en Tkinter de forma segura entre hilos."""
    try:
        win = widget.winfo_toplevel()
        if hasattr(win, "gui_queue"):
            win.gui_queue.put(callback)
            return
    except (tk.TclError, RuntimeError, Exception):
        return
    try:
        callback()
    except (tk.TclError, RuntimeError, Exception):
        pass

def get_safe_stats_file():
    """Obtiene la ruta de estadísticas resolviendo restricciones GPO locales."""
    t_dir = tempfile.gettempdir()
    test_file = os.path.join(t_dir, "ldac_stats_write_test.tmp")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return os.path.join(t_dir, "ldac_stats.json")
    except Exception:
        return os.path.join(INSTALL_DIR, "ldac_stats.json")
