# LDAC Audio Windows WSL2

[![Release](https://img.shields.io/github/v/release/nicolas/LDAC-Windows-WSL2?color=00e5ff&style=flat-square)](https://github.com/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue?style=flat-square)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![RAM Idle](https://img.shields.io/badge/RAM%20Idle-~15%20MB-blueviolet?style=flat-square)](#)

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
* **Three Selectable Profiles**: 
  * 🟢 **Extreme Quality (990 kbps)**: Audiophile mode for optimal wireless fidelity.
  * 🟡 **Stable Mode (660 kbps)**: Standard LDAC quality for high-interference environments (dense 2.4GHz/Wi-Fi zones).
  * 🔵 **Adaptive Mode (Auto)**: Dynamically scales quality matching signal capabilities.
* **Master Volume Integration**: Employs `PyCaw` to monitor Windows master volume changes and scales loopback audio digitally in C-speed (`audioop`) with zero latency.
* **Ultra-Lightweight Footprint**: Custom-engineered minimal Alpine Linux VM running on only **300 MB of allocated RAM** and ~234 MB disc space (compared to gigabytes of a standard VM).
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
6. Place desktop shortcuts for production and test environments.

### Step 3: Run the Application
Double-click the **`LDAC_LDAC_Audio.bat`** launcher on your desktop. 

The application will start in your system tray (bottom-right toolbar).
* **Right-click the icon** $\rightarrow$ Click **Configure Bluetooth** to scan and pair your headphones.
* Select your preferred LDAC quality (990kbps, 660kbps, Auto).
* Click **Start Transmission** to stream audio!

---

## 🛠️ Components List

* **`ldac_tray.py`**: The core system tray controller and GUI interface (Tkinter). Handles UAC escalations and WSL subsystem lifecycle.
* **`emisor_audio.py`**: High-performance WASAPI loopback audio capturer and UDP sender.
* **`receptor_audio.sh`**: Lightweight Alpine receiver script, managing PipeWire sockets and A2DP connection states.
* **`prepare_alpine.py`**: VM environment compiler to bootstrap dependencies.

---

## 📝 License

This project is open-source under the [MIT License](LICENSE). 

Special thanks to the developers of:
* **PyAudioWPatch** for the WASAPI Loopback interface.
* **PyCaw** for the Windows core audio control interface.
* **usbipd-win** for USB/IP Bluetooth sharing.
* **Alpine Linux** & **PipeWire** team for the high-performance audio engine.
