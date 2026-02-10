#!/bin/bash
# Setup script for car-client.py on Raspberry Pi Zero 2 W (Raspberry Pi OS Debian 11/12)
# Installs all required dependencies

set -e

echo "===================================="
echo "car-client.py Setup for Raspberry Pi Zero 2 W"
echo "===================================="
# Detect platform
ARCH=$(uname -m)
OS_CODENAME=$(grep VERSION_CODENAME /etc/os-release | cut -d= -f2 || true)
PI_MODEL=$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo "Unknown")
echo "Detected: $PI_MODEL ($ARCH) on ${OS_CODENAME:-unknown}"

# Update package list
echo ""
echo "[1/6] Updating package list..."
sudo apt-get update

# Choose libcamera package name based on OS availability
RPICAM_PKG="rpicam-apps"
if ! apt-cache show "$RPICAM_PKG" >/dev/null 2>&1; then
    RPICAM_PKG="libcamera-apps"
fi
if [ "$RPICAM_PKG" = "rpicam-apps" ]; then
    RPICAM_CMD="rpicam-vid"
else
    RPICAM_CMD="libcamera-vid"
fi

# Install Python 3 and pip
echo ""
echo "[2/6] Installing Python 3 and pip..."
sudo apt-get install -y python3 python3-pip

# Install GStreamer and related packages
echo ""
echo "[3/6] Installing GStreamer and WebRTC support..."
sudo apt-get install -y \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    libnice10 \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer-plugins-bad1.0-dev \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    python3-gst-1.0

# Install rpicam tools (libcamera)
echo ""
echo "[4/6] Installing rpicam-vid (libcamera)..."
sudo apt-get install -y "$RPICAM_PKG"

# Install Python dependencies
echo ""
echo "[5/6] Installing Python packages..."
sudo apt-get install -y \
    python3-serial \
    python3-gi

# websockets nie ma w apt, instalujemy z pip
sudo pip3 install --break-system-packages websockets

# Enable serial port (disable console on serial)
echo ""
echo "[6/7] Configuring serial port..."
if [ -f /boot/cmdline.txt ]; then
    # Remove both possible console args for Zero/Zero 2 W
    sudo sed -i \
        -e 's/console=serial0,115200 //g' \
        -e 's/console=serial0,115200//g' \
        -e 's/console=ttyAMA0,115200 //g' \
        -e 's/console=ttyAMA0,115200//g' \
        /boot/cmdline.txt
    # Normalize spaces
    sudo sed -i -e 's/  \+/ /g' /boot/cmdline.txt
    echo "Removed console from serial in /boot/cmdline.txt"
fi

# Enable UART in config.txt
if ! grep -q "^enable_uart=1" /boot/config.txt 2>/dev/null; then
    echo "enable_uart=1" | sudo tee -a /boot/config.txt
    echo "Added enable_uart=1 to /boot/config.txt"
fi

# Add user to dialout group for serial port access
echo ""
echo "Adding current user ($USER) to dialout group for serial port access..."
sudo usermod -a -G dialout $USER

# Configure DNS to prevent resolution issues
echo ""
echo "[7/7] Configuring DNS..."
if systemctl is-active --quiet systemd-resolved; then
    echo "Configuring systemd-resolved for reliable DNS..."
    sudo mkdir -p /etc/systemd/resolved.conf.d/
    cat <<EOF | sudo tee /etc/systemd/resolved.conf.d/dns.conf
[Resolve]
DNS=8.8.8.8 1.1.1.1
FallbackDNS=1.0.0.1 8.8.4.4
EOF
    sudo systemctl restart systemd-resolved
    echo "DNS configured via systemd-resolved"
else
    echo "Configuring static /etc/resolv.conf..."
    # Remove symlink if exists
    sudo rm -f /etc/resolv.conf
    cat <<EOF | sudo tee /etc/resolv.conf
nameserver 8.8.8.8
nameserver 1.1.1.1
nameserver 1.0.0.1
EOF
    # Prevent overwriting
    sudo chattr +i /etc/resolv.conf 2>/dev/null || true
    echo "DNS configured via /etc/resolv.conf (immutable)"
fi

echo ""
echo "===================================="
echo "Installation complete!"
echo "===================================="
echo ""
echo "IMPORTANT NOTES:"
echo "1. Serial port has been configured (/dev/serial0)"
echo "2. You may need to REBOOT for serial changes to take effect"
echo "3. After reboot, log out and back in for group changes to apply"
echo "4. Test camera with: $RPICAM_CMD -t 5000 --codec h264 -o test.h264"
echo "5. Test serial port with: ls -l /dev/serial0"
echo ""
echo "To run car-client.py:"
echo "  cd $(dirname $(readlink -f $0))"
echo "  python3 car-client.py"
echo ""
echo "Reboot now? (y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    sudo reboot
fi
