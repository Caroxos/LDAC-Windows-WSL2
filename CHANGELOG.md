# Registro de Errores Resueltos y Mejoras (Changelog)

Este documento detalla los problemas identificados y corregidos en el proyecto **LDAC Audio (Windows WSL2)**, sus causas de raíz, el impacto y los archivos modificados.

---

## 📋 Resumen de Problemas Corregidos

| ID | Componente | Severidad | Descripción del Error | Estado |
| :---: | :--- | :---: | :--- | :---: |
| **BUG-01** | `install.ps1` | **Crítica** | Fallo de instalación cuando WSL base no está presente o requiere reinicio; falsos positivos por errores silenciados. | **Resuelto** |
| **BUG-02** | `uninstall.ps1` | **Crítica** | No limpiaba `.wslconfig`, dejando el kernel apuntando a una ruta eliminada y rompiendo todas las VMs de WSL2. | **Resuelto** |
| **BUG-03** | `wsl_manager.py` | **Alta** | `NameError: name 'shutil' is not defined` al validar `usbipd` debido a importación faltante. | **Resuelto** |
| **BUG-04** | `emisor_audio.py` / `receptor_audio.sh` | **Alta** | Desincronización de frecuencia de muestreo (44.1kHz vs 48kHz) causando distorsión de tono/velocidad ("efecto ardilla"). | **Resuelto** |
| **BUG-05** | `stream_manager.py` | **Media** | Inyección de scripts con retornos de carro Windows (`\r\n`) provocando fallos de sintaxis en Alpine Linux (`/bin/ash`). | **Resuelto** |
| **BUG-06** | `emisor_audio.py` | **Media** | Incompatibilidad con Python 3.13+ debido a la eliminación de `audioop` (PEP 594). | **Resuelto** |

---

## 🔍 Detalle Técnico de los Errores

### 1. BUG-01: Auto-detección de WSL y robustez en el Instalador
* **Archivo:** [`install.ps1`](https://github.com/Caroxos/LDAC-Windows-WSL2/blob/main/install.ps1)
* **Causa:** 
  1. `wsl.exe --update` y `wsl.exe --import` fallaban si el paquete base de WSL no estaba instalado previamente en Windows 10/11.
  2. En PowerShell, los ejecutables nativos no lanzan excepciones capturadas por bloques `try/catch` tradicionales; al usar `| Out-Null`, los errores se ignoraban y se reportaba éxito falso.
  3. Al solicitar elevación UAC, la nueva ventana se abría en `C:\Windows\System32` perdiendo la ruta del script.
  4. El prompt de confirmación cancelaba inmediatamente si el usuario presionaba la tecla `Enter`.
* **Solución:**
  * Se añadió verificación de estado (`wsl.exe --status`) e instalación automática de la base con `wsl.exe --install --no-distribution`.
  * Se verifica `$LASTEXITCODE` y el código `3010` (reinicio pendiente de Windows).
  * Se fija el `WorkingDirectory` en la auto-elevación.
  * El prompt ahora acepta `Enter` por defecto (y variantes `y/yes/s/si/sí`).

---

### 2. BUG-02: Restauración de `.wslconfig` en el Desinstalador
* **Archivo:** [`uninstall.ps1`](https://github.com/Caroxos/LDAC-Windows-WSL2/blob/main/uninstall.ps1)
* **Causa:** Al desinstalar, el script borraba `C:\LDAC_Audio` pero dejaba `%USERPROFILE%\.wslconfig` con la línea `kernel=C:\LDAC_Audio\kernel\bzImage`. Como el archivo del kernel ya no existía, cualquier otra distribución de Linux (Ubuntu, Debian, etc.) fallaba al intentar arrancar en Windows.
* **Solución:**
  * Se implementó un analizador que busca y remueve de forma segura la entrada del kernel de LDAC en `.wslconfig`.
  * Si el archivo queda vacío o solo con la sección vacía, se elimina por completo para restaurar la configuración por defecto de Windows.
  * Se aplicó la misma tolerancia de prompt y fijación de directorio de trabajo.

---

### 3. BUG-03: Excepción no controlada por falta de `shutil` en `wsl_manager.py`
* **Archivo:** [`wsl_manager.py`](https://github.com/Caroxos/LDAC-Windows-WSL2/blob/main/wsl_manager.py)
* **Causa:** En la línea 87 se invocaba `shutil.which("usbipd")` sin haber importado el módulo `shutil` en el encabezado, generando un `NameError` inmediato en caso de que `USBIPD` no estuviera en la ruta fija.
* **Solución:**
  * Se añadió `import shutil` al inicio del archivo.
  * Se actualizó la URL de ayuda a la release oficial de `usbipd-win`.

---

### 4. BUG-04 & BUG-06: Sincronización de Audio y Compatibilidad Python 3.13+
* **Archivos:** [`emisor_audio.py`](https://github.com/Caroxos/LDAC-Windows-WSL2/blob/main/emisor_audio.py) y [`receptor_audio.sh`](https://github.com/Caroxos/LDAC-Windows-WSL2/blob/main/receptor_audio.sh)
* **Causa:**
  1. `emisor_audio.py` capturaba el audio a la frecuencia nativa de Windows (comúnmente 44.1 kHz, 96 kHz o 192 kHz), pero `receptor_audio.sh` ejecutaba `pacat` con `--rate=48000 --channels=2` fijo. Esto provocaba aceleración/ralentización y deformación del tono del audio.
  2. En Python 3.13+, el módulo estándar `audioop` fue eliminado (PEP 594), impidiendo la ejecución en entornos modernos.
* **Solución:**
  * Se estandarizó la captura en `emisor_audio.py` a 48000 Hz estéreo con fallback automático si el hardware lo requiere.
  * Se parametrizaron `SAMPLE_RATE` y `CHANNELS` en `receptor_audio.sh`.
  * Se implementó una función `scale_volume()` con fallback manual en Python puro usando `array('h')` en caso de que `audioop` no esté presente.

---

### 5. BUG-05: Sanitización de saltos de línea Windows (`CRLF` -> `LF`)
* **Archivo:** [`stream_manager.py`](https://github.com/Caroxos/LDAC-Windows-WSL2/blob/main/stream_manager.py)
* **Causa:** Al inyectar el script shell `receptor_audio.sh` hacia la máquina virtual Alpine Linux mediante `cat > /root/receptor_audio.sh`, se conservaban los saltos de línea Windows `\r\n`. Al ejecutarse en Alpine con `/bin/ash`, el intérprete fallaba al encontrar caracteres `\r`.
* **Solución:**
  * Se aplica `content.replace('\r\n', '\n').replace('\r', '\n')` antes de transmitir el archivo al subproceso de WSL.

---

## 🚀 Historial de Commits en GitHub (`main`)

| Hash | Mensaje de Commit | Archivos Afectados |
| :---: | :--- | :--- |
| [`1ceaeb2`](https://github.com/Caroxos/LDAC-Windows-WSL2/commit/1ceaeb2eaf97b2638ed29e0da8b49bbb3dd3462e) | `fix(installer): improve WSL auto-install, prompt handling, and native error detection` | `install.ps1` |
| [`3ac1d26`](https://github.com/Caroxos/LDAC-Windows-WSL2/commit/3ac1d2655968516cf442cdcf4614f7aa992803df) | `fix(uninstaller): restore .wslconfig, improve confirmation and elevation` | `uninstall.ps1` |
| [`1cbcf41`](https://github.com/Caroxos/LDAC-Windows-WSL2/commit/1cbcf4158a630537274e571dc1c743f72ee3a8af) | `fix(wsl_manager): import missing shutil and fix usbipd release URL` | `wsl_manager.py` |
| [`a065805`](https://github.com/Caroxos/LDAC-Windows-WSL2/commit/a065805466e07a5f65dfdb68b2c9bc5edac67695) | `fix(stream_manager): sanitize CRLF line endings when copying script to WSL` | `stream_manager.py` |
| [`c3f49e3`](https://github.com/Caroxos/LDAC-Windows-WSL2/commit/c3f49e35bc7b2870379b67876c6c8e9ca182ce74) | `fix(emisor_audio): add Python 3.13 audioop fallback and standardize 48kHz audio` | `emisor_audio.py` |
| [`15cc8fc`](https://github.com/Caroxos/LDAC-Windows-WSL2/commit/15cc8fc443ed9f6c7bf5b7624a50417f6107f385) | `fix(receptor_audio): support configurable sample rate and channels in pacat` | `receptor_audio.sh` |
