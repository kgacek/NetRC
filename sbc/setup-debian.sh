#!/bin/bash
# Setup script for car-client.py on Debian 11 (Raspberry Pi OS)
# Installs all required dependencies

set -e

echo "===================================="
echo "car-client.py Setup for Debian 11"
echo "===================================="

# Update package list
echo ""
echo "[1/6] Updating package list..."
sudo apt-get update

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
    gstreamer1.0-nice \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer-plugins-bad1.0-dev \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    python3-gst-1.0

# Install rpicam tools (libcamera)
echo ""
echo "[4/6] Installing rpicam-vid (libcamera)..."
sudo apt-get install -y libcamera-apps

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
echo "[6/6] Configuring serial port..."
if [ -f /boot/cmdline.txt ]; then
    sudo sed -i 's/console=serial0,115200 //' /boot/cmdline.txt
    echo "Removed console from serial0 in /boot/cmdline.txt"
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

echo ""
echo "===================================="
echo "Installation complete!"
echo "===================================="
echo ""
echo "IMPORTANT NOTES:"
echo "1. Serial port has been configured (/dev/serial0)"
echo "2. You may need to REBOOT for serial changes to take effect"
echo "3. After reboot, log out and back in for group changes to apply"
echo "4. Test rpicam-vid with: rpicam-vid -t 5000 --codec h264 -o test.h264"
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
