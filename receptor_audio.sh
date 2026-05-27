#!/bin/ash
echo '=== UDP AUDIO RECEIVER (WSL2) ==='

MAC_ADDRESS=${1:-"01:02:03:04:1E:19"}
LDAC_MODE=${2:-"hq"}

# Verify if the system is already up and headphones are connected
if pgrep pipewire >/dev/null 2>&1 && pgrep wireplumber >/dev/null 2>&1 && bluetoothctl info "$MAC_ADDRESS" 2>/dev/null | grep -q "Connected: yes"; then
    echo "Active servers and headphones already connected. Directing audio stream directly..."
    # Adjust volume
    pactl set-sink-volume @DEFAULT_SINK@ 80% >/dev/null 2>&1
    # Run the receiver directly
    nc -l -u -p 5005 | pacat --playback --format=s16le --rate=48000 --channels=2
    exit 0
fi

echo 'Listening on UDP port 5005...'
echo 'Received data will be routed directly to PipeWire.'
echo 'To cancel, press Ctrl+C.'

# Load kernel modules just in case
modprobe vhci-hcd >/dev/null 2>&1
modprobe btusb >/dev/null 2>&1

# Clean previous orphaned processes and sockets
killall -9 nc pacat pipewire pipewire-pulse wireplumber 2>/dev/null
rm -rf /tmp/runtime-root/* /tmp/runtime-root/.* 2>/dev/null


# Start dbus and bluetoothd if not running
mkdir -p /run/dbus
[ -f /var/run/dbus/pid ] || dbus-daemon --system --fork >/dev/null 2>&1
pgrep bluetoothd >/dev/null || /usr/lib/bluetooth/bluetoothd & >/dev/null 2>&1

# Start PipeWire and PipeWire-Pulse in the background
export XDG_RUNTIME_DIR=/tmp/runtime-root
export PULSE_SERVER=unix:/tmp/runtime-root/pulse/native
mkdir -p $XDG_RUNTIME_DIR
chmod 700 $XDG_RUNTIME_DIR

# Set LDAC quality in WirePlumber dynamically if argument $2 is received
LDAC_MODE=${2:-"hq"}

# Clear any previous residue in the root folder due to the $HOME bug inherited from Windows
rm -f /root/.config/wireplumber/wireplumber.conf.d/10-bluez.conf 2>/dev/null

# Use /etc/wireplumber which is the system path, ensuring it works regardless of the $HOME variable
mkdir -p /etc/wireplumber/wireplumber.conf.d
cat <<EOF > /etc/wireplumber/wireplumber.conf.d/10-bluez.conf
monitor.bluez.rules = [
  {
    matches = [
      {
        device.name = "~bluez_card.*"
      }
    ]
    actions = {
      update-props = {
        bluez5.a2dp.ldac.quality = "$LDAC_MODE"
      }
    }
  }
]
EOF

pgrep pipewire >/dev/null || pipewire >/dev/null 2>&1 &
pgrep pipewire-pulse >/dev/null || pipewire-pulse >/dev/null 2>&1 &
pgrep wireplumber >/dev/null || wireplumber >/dev/null 2>&1 &

# Wait for PipeWire-Pulse communication socket to be physically ready
SOCKET_PATH="/tmp/runtime-root/pulse/native"
echo "Waiting for the audio server to be ready..."
for i in $(seq 1 20); do
    [ -S "$SOCKET_PATH" ] && break
    sleep 0.5
done

if [ ! -S "$SOCKET_PATH" ]; then
    echo "[ERROR] The audio server could not be started in time."
    exit 1
fi
echo "Audio server ready."

# Wait for Linux kernel to recognize the redirected Bluetooth adapter (hci0)
echo "Waiting for Bluetooth adapter..."
for i in $(seq 1 10); do
    [ -d "/sys/class/bluetooth/hci0" ] && break
    sleep 1
done

if [ ! -d "/sys/class/bluetooth/hci0" ]; then
    echo "[ERROR] Bluetooth adapter hci0 did not appear in time."
    exit 1
fi
echo "Bluetooth adapter ready."

# Restart WirePlumber to ensure it discovers hci0 and registers A2DP endpoints in D-Bus
killall -9 wireplumber 2>/dev/null
wireplumber >/dev/null 2>&1 &
sleep 1.5

# Ensure Bluetooth controller is powered on in Linux
echo "power on" | bluetoothctl >/dev/null 2>&1
sleep 1

# Attempt to connect to classic headphones (up to 3 connection attempts)
MAC_ADDRESS=${1:-"01:02:03:04:1E:19"}
echo "Establishing classic audio link with $MAC_ADDRESS..."
for i in 1 2 3; do
    if echo "info $MAC_ADDRESS" | bluetoothctl | grep -q "Connected: yes"; then
        echo "Headphones connected successfully."
        break
    fi
    echo "connect $MAC_ADDRESS" | bluetoothctl >/dev/null 2>&1
    sleep 2
done

# Give 1 second for PipeWire to recognize the audio device
sleep 1

# Set default volume to 80% to avoid it being inaudible
pactl set-sink-volume @DEFAULT_SINK@ 80% >/dev/null 2>&1

# Listen on port 5005 and play with pacat
nc -l -u -p 5005 | pacat --playback --format=s16le --rate=48000 --channels=2
