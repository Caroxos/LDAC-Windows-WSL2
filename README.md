# LDAC Audio Windows WSL2

[![Release](https://img.shields.io/github/v/release/Caroxos/LDAC-Windows-WSL2?color=00e5ff&style=flat-square)](https://github.com/Caroxos/LDAC-Windows-WSL2/releases)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue?style=flat-square)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![RAM Limit](https://img.shields.io/badge/RAM%20Limit-300%20MB-blueviolet?style=flat-square)](#)

Fully automated, high-resolution **LDAC (990 kbps)** wireless audio transmission system for Windows 10 & 11 via WSL2 Alpine Linux. 

A **100% free**, open-source alternative to commercial A2DP Bluetooth drivers ($6–$10 USD) or dangerous unsigned kernel drivers. 

---

## 🎧 Architecture Overview

```
                   WINDOWS HOST (Windows 10/11)
  ┌──────────────────────────────────────────────────────────┐
  │  Windows Audio Engine (WASAPI System Sound)              │
  │                      │ (Loopback Capture)                │
  │                      ▼                                   │
  │  emisor_audio.py (WASAPI Loopback -> PyAudioWPatch)      │
  │  ├── PyCaw (Tracks Windows Master Volume Slider in real-time) │
  │  └── Scaled Digital Samples -> UDP Packet Stream         │
  └──────────────────────┬───────────────────────────────────┘
                         │ (WSL2 Internal Virtual Network)
                         ▼
             WSL2 GUEST (Alpine Linux VM - 300MB RAM Limit)
  ┌──────────────────────────────────────────────────────────┐
  │  receptor_audio.sh (Listens on UDP Port)                 │
  │                      │                                   │
  │                      ▼ (PulseAudio pacat Pipe)           │
  │  PipeWire / WirePlumber (Official LDAC 990kbps Encoder)│
  │                      │                                   │
  │                      ▼ (A2DP AVDTP Stream)               │
  │  BlueZ Stack (bluetoothd & bluetoothctl)                 │
  └──────────────────────┬───────────────────────────────────┘
                         │ (Redirection via usbipd-win)
                         ▼
             PHYSICAL HARDWARE & CHIPSETS
  ┌──────────────────────────────────────────────────────────┐
  │  PCIe/USB Bluetooth Radio Dongle (Shared via USBIPD)     │
  └──────────────────────┬───────────────────────────────────┘
                         │ (Bluetooth LDAC 990 kbps Wireless)
                         ▼
       Audiophile Bluetooth Headphones / Receivers 
       (e.g., compatible headsets, etc.)
```

---

## ✨ Features

* **True Audiophile Quality (990 kbps)**: Employs the official open-source LDAC encoder to stream uncompressed-like high-resolution audio.
* **Highly Stable with Low Latency**: Engineered for a highly stable wireless connection with a low delay of **only ~80ms** (ideal for music, video playback, and general desktop use).
* **Three Selectable Profiles**: 
  * 🟢 **Extreme Quality (990 kbps)**: Audiophile mode for optimal wireless fidelity.
  * 🟡 **Stable Mode (660 kbps)**: Standard LDAC quality for high-interference environments (dense 2.4GHz/Wi-Fi zones).
  * 🔵 **Adaptive Mode (Auto)**: Dynamically scales quality matching signal capabilities.
* **Master Volume Integration**: Employs `PyCaw` to monitor Windows master volume changes and scales loopback audio digitally in C-speed (`audioop`) with zero latency.
* **Ultra-Lightweight Footprint**: Custom-engineered minimal Alpine Linux VM running on only **300 MB of allocated RAM** and ~234 MB disc space. *(Note: This RAM limit is the absolute minimum possible and cannot be decreased any further due to WSL2 fixed hypervisor overhead, such as network virtualization bridges and filesystem sharing).*
* **Automated USB Redirection**: Integrates `usbipd-win` to dynamically discover physical PCIe/USB Bluetooth hardware and share it automatically with WSL2.
* **Dynamic GUI Tray Application**: Keep track of the connection state, select audio profiles, and monitor real-time stream status (UDP bitrate, active headset descriptions, active codec) through a beautiful dark/cyan Windows system tray widget.

---

## 🚀 Quick Start & Installation

### Prerequisites
1. A PC running **Windows 10 (Build 19041 or higher)** or **Windows 11**.
2. A compatible Bluetooth USB Dongle or motherboard PCIe Bluetooth card.
3. LDAC-capable headphones.

### Step 1: Download the Package
Go to the **[Releases](https://github.com/)** page of this repository and download the latest **`LDAC_En.zip`** archive.

### Step 2: Run the Installer
Extract the `.zip` archive to any directory, open **PowerShell as an Administrator**, navigate to the extracted directory, and run:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; & ".\install.ps1"
```

The automated installer will:
1. Enable necessary Windows features (WSL2, Virtual Machine Platform).
2. Install or update the WSL virtual engine.
3. Install `usbipd-win` silently (offline installer included).
4. Extract the ultra-optimized Alpine Linux environment to `C:\LDAC_Audio`.
5. Write the correct RAM policies (.wslconfig) and custom audio Bluetooth kernels.
6. Place a desktop shortcut for the production environment.

### Step 3: Run the Application
Double-click the **`LDAC_Audio.exe`** shortcut on your desktop (or in your installation folder).

The application will start directly in your system tray (bottom-right toolbar).
* **Right-click the icon** $\rightarrow$ Click **Configure Bluetooth** to scan and pair your headphones.
* Select your preferred LDAC quality (990 kbps, 660 kbps, Auto).
* **Automatic Streaming / Auto-Healing**: If your headphones are already connected physically to Windows/WSL, opening the Bluetooth configuration window will automatically auto-align and kickstart the stream with zero clicks.

---

## 🛡️ Antivirus False Positives (Windows Defender / VirusTotal)

Because `LDAC_Audio.exe` is compiled as a standalone binary using **PyInstaller** (to bundle Python, PyAudio, and Tkinter without requiring you to install any runtime), some security scanners on **VirusTotal** (such as Microsoft Defender's heuristic engine) may flag it as a generic threat like **`Trojan:Win32/Wacatac.B!ml`** or similar.

* **What does `!ml` mean?** The `!ml` suffix stands for **Machine Learning** heuristical analysis. It is an automated statistical model flag triggered by unsigned local binaries that execute subprocesses (like attaching USB adapters via `usbipd.exe`).
* **Is it safe?** **Yes, 100% safe.** The entire source code is open and transparent. Since you have the exact Python modules in the repository, you can verify every single line of code.
* **Resolution**: Simply add a local folder exclusion in Windows Defender for `C:\LDAC_Audio` or the `LDAC_Audio.exe` binary.

---

## 🛠️ Modular Architecture Components

The application is structured under a clean, modular architecture:
* **`main.py`**: The core system tray controller and icon lifecycle manager (pystray).
* **`gui_bt_manager.py`**: Bluetooth configuration window and auto-healing connection poller.
* **`stream_manager.py`**: Controls the audio capture/transmission threads and PipeWire bitrates.
* **`context.py`**: Maintains app state transitions and JSON profiles in a thread-safe context.
* **`wsl_manager.py`**: Controls the WSL Alpine VM lifecycle, `usbipd` adapter attachments, and dbus daemon probes.
* **`bt_scanner.py`**: Handles asynchronous Bluetooth radio scans, pairing, and D-Bus parsing.
* **`emisor_audio.py`**: Captured loopback WASAPI audio and streams it locally over UDP.
* **`receptor_audio.sh`**: Linux shell script executing in Alpine to pipe incoming UDP audio to PipeWire sinks.
* **`sys_helpers.py`**: Windows native OS helpers, single-instance named kernel mutexes, and Job Objects.
* **`logger.py`**: Universal timed auditing logger mapping all executions to `logs/ldac_session_*.log`.

---

## 📝 License

This project is open-source under the [MIT License](LICENSE). 

Special thanks to the developers of:
* **PyAudioWPatch** for the WASAPI Loopback interface.
* **PyCaw** for the Windows core audio control interface.
* **usbipd-win** for USB/IP Bluetooth sharing.
* **Alpine Linux** & **PipeWire** team for the high-performance audio engine.
