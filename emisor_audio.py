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
import audioop
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

UDP_PORT   = 5005
CHUNK      = 1024
STATS_FILE = os.path.join(tempfile.gettempdir(), "ldac_stats.json")

def get_wsl_ip():
    """Descubre dinámicamente la dirección IP interna de WSL2 (Alpine)"""
    try:
        # Ejecutar comando para ver la IP de eth0 en Alpine
        output = subprocess.check_output("wsl -d Alpine ip addr show eth0", shell=True, stderr=subprocess.DEVNULL).decode("utf-8")
        match = re.search(r"inet\s+([0-9.]+)", output)
        if match:
            ip = match.group(1)
            print(f"[INFO] IP de WSL2 (Alpine) detectada automáticamente: {ip}")
            return ip
    except Exception as e:
        pass
    
    print("[WARN] No se pudo detectar la IP de WSL2. Usando localhost (127.0.0.1)")
    return "127.0.0.1"

def main():
    print("=== EMISOR DE AUDIO WASAPI LOOPBACK (WINDOWS -> WSL2) ===")
    
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
        print(f"[INFO] Mezclador de volumen de Windows detectado. Volumen inicial: {int(volume_state[0]*100)}%")
    except Exception as e:
        print(f"[WARN] No se pudo vincular al mezclador de volumen de Windows: {e}")
        
    # 3. Inicializar PyAudio
    p = pyaudio.PyAudio()
    
    try:
        # Obtener el API de WASAPI
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except IndexError:
            print("[ERROR] WASAPI no está disponible en este sistema.")
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
            print("[INFO] Buscando cualquier dispositivo Loopback activo...")
            for loopback in p.get_loopback_device_info_generator():
                loopback_device = loopback
                break
                
        if not loopback_device:
            print("[ERROR] No se pudo encontrar ningún dispositivo de captura Loopback (WASAPI).")
            return
            
        print(f"[INFO] Capturando de: {loopback_device['name']}")
        
        # Configurar parámetros basados en el dispositivo
        rate = int(loopback_device["defaultSampleRate"])
        channels = loopback_device["maxInputChannels"]
        
        print(f"[INFO] Configuración de audio: {rate} Hz, {channels} canales, formato de 16 bits")
        
        # Contador de bytes enviados (accedido desde callback + hilo principal)
        bytes_counter = [0]

        # Callback para enviar audio en tiempo real por UDP
        def callback(in_data, frame_count, time_info, status):
            try:
                factor = volume_state[0]
                if factor < 0.99:
                    scaled_data = audioop.mul(in_data, 2, factor)
                else:
                    scaled_data = in_data
                sock.sendto(scaled_data, (wsl_ip, UDP_PORT))
                bytes_counter[0] += len(scaled_data)
            except Exception:
                pass
            return (in_data, pyaudio.paContinue)

        # Abrir el stream de WASAPI Loopback
        stream = p.open(format=pyaudio.paInt16,
                        channels=channels,
                        rate=rate,
                        input=True,
                        input_device_index=loopback_device["index"],
                        frames_per_buffer=CHUNK,
                        stream_callback=callback)

        print(f"[ÉXITO] Transmitiendo audio en tiempo real a {wsl_ip}:{UDP_PORT}...")
        print("Presiona Ctrl+C para detener el emisor.")
        
        stream.start_stream()

        last_stats_time  = time.time()
        last_bytes       = 0
        last_volume_pct  = -1

        while stream.is_active():
            now = time.time()
            elapsed = now - last_stats_time

            if elapsed >= 1.0:
                sent = bytes_counter[0]
                delta_bytes = sent - last_bytes
                udp_kbps = int((delta_bytes * 8) / (elapsed * 1000))
                last_bytes      = sent
                last_stats_time = now

                # Escribir estadisticas al archivo compartido
                try:
                    with open(STATS_FILE, "w") as f:
                        json.dump({
                            "udp_kbps":  udp_kbps,
                            "volume":    int(volume_state[0] * 100),
                            "rate":      rate,
                            "channels":  channels,
                            "timestamp": now,
                        }, f)
                except Exception:
                    pass

            # Actualizar volumen cada 100ms
            if volume_control:
                try:
                    volume_state[0] = volume_control.GetMasterVolumeLevelScalar()
                except Exception:
                    pass
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n[INFO] Deteniendo transmisión por petición del usuario.")
    except Exception as e:
        print(f"\n[ERROR] Ocurrió un fallo en el emisor: {e}")
    finally:
        if 'stream' in locals() and stream.is_active():
            stream.stop_stream()
            stream.close()
        p.terminate()
        sock.close()
        print("[INFO] Recursos de audio y red cerrados correctamente.")

if __name__ == "__main__":
    main()
