import warnings
# Silenciar advertencias de deprecacion de audioop antes de importarlo
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pyaudiowpatch as pyaudio
import socket
import subprocess
import re
import sys
import time
import json
import tempfile
import os
import array
from logger import WSL_DISTRO

# Compatibilidad con Python 3.13+ (audioop eliminado en PEP 594)
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
    except ImportError:
        audioop = None

def scale_volume(data, factor):
    """Escala el volumen PCM de 16-bit de forma segura y eficiente."""
    if factor >= 0.99:
        return data
    if audioop is not None:
        return audioop.mul(data, 2, factor)
    # Fallback puro en Python usando array de enteros de 16 bits
    try:
        samples = array.array('h', data)
        for i in range(len(samples)):
            samples[i] = int(samples[i] * factor)
        return samples.tobytes()
    except Exception:
        return data

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# Force UTF-8 output to prevent UnicodeEncodeError on non-Latin Windows locales (e.g. cp950)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UDP_PORT   = 5005
CHUNK      = 1024

import sys
if getattr(sys, "frozen", False):
    INSTALL_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))

def get_safe_stats_file():
    t_dir = tempfile.gettempdir()
    test_file = os.path.join(t_dir, "ldac_stats_write_test.tmp")
    try:
        # Validar permisos reales de escritura en la carpeta temporal
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return os.path.join(t_dir, "ldac_stats.json")
    except Exception:
        # Fallback al directorio local del programa ante GPO restrictivas
        return os.path.join(INSTALL_DIR, "ldac_stats.json")

STATS_FILE = get_safe_stats_file()

def get_wsl_ip():
    """Descubre dinámicamente la dirección IP interna de WSL2 (Alpine)"""
    try:
        # Ejecutar comando para ver la IP de eth0 en Alpine
        output = subprocess.check_output("wsl -d " + WSL_DISTRO + " ip addr show eth0", shell=True, stderr=subprocess.DEVNULL).decode("utf-8")
        match = re.search(r"inet\s+([0-9.]+)", output)
        if match:
            ip = match.group(1)
            print(f"[INFO] WSL2 (Alpine) IP detected automatically: {ip}")
            return ip
    except Exception as e:
        pass
    
    print("[WARN] Could not detect WSL2 IP. Using localhost (127.0.0.1)")
    return "127.0.0.1"

def main():
    print("=== WASAPI LOOPBACK AUDIO EMITTER (WINDOWS -> WSL2) ===")
    
    # 1. Obtener IP de destino
    wsl_ip = get_wsl_ip()
    
    # 2. Inicializar Socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Estado del volumen de Windows (lista mutable para ser modificada en el hilo principal y leída en el callback)
    volume_state = [1.0]
    volume_control = None
    
    try:
        devices = AudioUtilities.GetSpeakers()
        volume_control = devices.EndpointVolume
        volume_state[0] = volume_control.GetMasterVolumeLevelScalar()
        print(f"[INFO] Windows volume mixer detected. Initial volume: {int(volume_state[0]*100)}%")
    except Exception as e:
        print(f"[WARN] Could not bind to Windows volume mixer: {e}")
        
    # 3. Inicializar PyAudio
    p = pyaudio.PyAudio()
    
    try:
        # Obtener el API de WASAPI
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except IndexError:
            print("[ERROR] WASAPI is not available on this system.")
            return

        # Buscar el dispositivo de salida por defecto y su loopback
        default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        
        loopback_device = None
        # Buscar el loopback de nuestros altavoces por defecto
        for loopback in p.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                loopback_device = loopback
                break
                
        if not loopback_device:
            print("[INFO] Searching for any active Loopback device...")
            for loopback in p.get_loopback_device_info_generator():
                loopback_device = loopback
                break
                
        if not loopback_device:
            print("[ERROR] Could not find any Loopback capture device (WASAPI).")
            return
            
        print(f"[INFO] Capturing from: {loopback_device['name']}")
        
        # Configurar parámetros basados en el dispositivo
        native_rate = int(loopback_device.get("defaultSampleRate", 48000))
        native_channels = int(loopback_device.get("maxInputChannels", 2))
        
        # Contador de bytes enviados (accedido desde callback + hilo principal)
        bytes_counter = [0]

        # Callback para enviar audio en tiempo real por UDP
        def callback(in_data, frame_count, time_info, status):
            try:
                factor = volume_state[0]
                scaled_data = scale_volume(in_data, factor)
                sock.sendto(scaled_data, (wsl_ip, UDP_PORT))
                bytes_counter[0] += len(scaled_data)
            except Exception:
                pass
            return (in_data, pyaudio.paContinue)

        # Abrir el stream de WASAPI Loopback (preferir 48000 Hz estéreo para coincidir con el receptor pacat)
        rate = 48000
        channels = 2
        try:
            stream = p.open(format=pyaudio.paInt16,
                            channels=channels,
                            rate=rate,
                            input=True,
                            input_device_index=loopback_device["index"],
                            frames_per_buffer=CHUNK,
                            stream_callback=callback)
        except Exception:
            # Si el hardware exige exclusivamente su formato nativo, hacer fallback
            rate = native_rate
            channels = min(native_channels, 2)
            stream = p.open(format=pyaudio.paInt16,
                            channels=channels,
                            rate=rate,
                            input=True,
                            input_device_index=loopback_device["index"],
                            frames_per_buffer=CHUNK,
                            stream_callback=callback)

        print(f"[INFO] Audio stream active: {rate} Hz, {channels} channels, 16-bit format")

        print(f"[OK] Streaming audio in real-time to {wsl_ip}:{UDP_PORT}...")
        print("Press Ctrl+C to stop the emitter.")
        
        stream.start_stream()

        last_stats_time  = time.time()
        last_bytes       = 0
        last_volume_pct  = -1

        try:
            while stream.is_active():
                now = time.time()
                elapsed = now - last_stats_time

                if elapsed >= 1.0:
                    sent = bytes_counter[0]
                    delta_bytes = sent - last_bytes
                    udp_kbps = int((delta_bytes * 8) / (elapsed * 1000))
                    last_bytes      = sent
                    last_stats_time = now

                    # Escribir estadísticas de forma atómica para evitar bloqueos y parpadeos en la UI
                    try:
                        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(STATS_FILE), prefix="ldac_stats_tmp")
                        with os.fdopen(temp_fd, "w") as f:
                            json.dump({
                                "udp_kbps":  udp_kbps,
                                "volume":    int(volume_state[0] * 100),
                                "rate":      rate,
                                "channels":  channels,
                                "timestamp": now,
                            }, f)
                        os.replace(temp_path, STATS_FILE)
                    except Exception:
                        if 'temp_path' in locals() and os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except Exception:
                                pass

                # Actualizar volumen cada 100ms
                if volume_control:
                    try:
                        volume_state[0] = volume_control.GetMasterVolumeLevelScalar()
                    except Exception:
                        pass
                time.sleep(0.1)
        except Exception as stream_err:
            print(f"\n[ERROR] Audio stream experienced a failure: {stream_err}")
            
    except KeyboardInterrupt:
        print("\n[INFO] Stopping transmission by user request.")
    except Exception as e:
        print(f"\n[ERROR] Emitter encountered a failure: {e}")
    finally:
        if 'stream' in locals() and stream.is_active():
            stream.stop_stream()
            stream.close()
        p.terminate()
        sock.close()
        print("[INFO] Audio and network resources closed successfully.")

if __name__ == "__main__":
    main()
