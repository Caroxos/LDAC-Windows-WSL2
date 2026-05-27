import urllib.request
import zipfile
import os
import sys

URL = "https://github.com/duncanthrax/scream/releases/download/4.0/Scream4.0.zip"
ZIP_DEST = "Scream4.0.zip"
EXTRACT_DIR = "scream"

def main():
    print("Iniciando descarga de Scream 4.0 Virtual Audio Card...")
    print(f"Desde: {URL}")
    print(f"Hacia: {os.path.abspath(ZIP_DEST)}")
    
    try:
        def progress_callback(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(100.0, (downloaded / total_size) * 100.0) if total_size > 0 else 0
            sys.stdout.write(f"\rProgreso: {percent:.1f}% ({downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB)")
            sys.stdout.flush()

        urllib.request.urlretrieve(URL, ZIP_DEST, progress_callback)
        print("\n¡Descarga completada con éxito!")
        
        print(f"Extrayendo archivo ZIP en '{EXTRACT_DIR}'...")
        if not os.path.exists(EXTRACT_DIR):
            os.makedirs(EXTRACT_DIR)
            
        with zipfile.ZipFile(ZIP_DEST, 'r') as zip_ref:
            zip_ref.extractall(EXTRACT_DIR)
        print("¡Extracción completada con éxito!")
        
        # Eliminar el zip original
        os.remove(ZIP_DEST)
        print("Archivo ZIP temporal eliminado.")
        
    except Exception as e:
        print(f"\nError durante el proceso: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
