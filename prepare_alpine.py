import urllib.request
import os
import sys

URL = "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-minirootfs-3.20.0-x86_64.tar.gz"
DEST = "alpine-rootfs.tar.gz"

def main():
    print("Iniciando descarga de Alpine Linux Minirootfs (v3.20)...")
    print(f"Desde: {URL}")
    print(f"Hacia: {os.path.abspath(DEST)}")
    
    try:
        def progress_callback(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(100.0, (downloaded / total_size) * 100.0) if total_size > 0 else 0
            sys.stdout.write(f"\rProgreso: {percent:.1f}% ({downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB)")
            sys.stdout.flush()

        urllib.request.urlretrieve(URL, DEST, progress_callback)
        print("\n¡Descarga completada con éxito!")
        print(f"Archivo guardado como '{DEST}' (Tamaño: {os.path.getsize(DEST) / (1024*1024):.2f} MB)")
    except Exception as e:
        print(f"\nError durante la descarga: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
