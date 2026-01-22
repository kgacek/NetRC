#!/bin/bash
# Setup script for car-client.py on Debian 11 (Radxa A7Z)
# Installs all required dependencies

set -e

echo "===================================="
echo "car-client.py Setup for Radxa A7Z"
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
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    python3-gst-1.0

# Install v4l2 and ffmpeg for camera on Radxa A7Z
echo ""
echo "[4/6] Installing camera tools (v4l2, ffmpeg)..."
sudo apt-get install -y \
    v4l-utils \
    ffmpeg

# Install Python dependencies
echo ""
echo "[5/6] Installing Python packages..."
sudo pip3 install \
    websockets \
    pyserial \
    pygobject

# Enable serial port (disable console on serial)
echo ""
echo "[6/6] Configuring serial port..."
echo "NOTE: Radxa A7Z typically uses /dev/ttyS0, /dev/ttyS1, or /dev/ttyUSB0"
echo "Check your board documentation for the correct UART device."
echo "Console on serial might need to be disabled in /boot/extlinux/extlinux.conf"

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
echo "1. Check available serial ports: ls -l /dev/ttyS* /dev/ttyUSB*"
echo "2. List camera devices: v4l2-ctl --list-devices"
echo "3. Test camera: ffmpeg -f v4l2 -i /dev/video0 -t 5 -c:v h264 test.h264"
echo "4. Update UART_DEV in car-client.py to match your serial port"
echo "5. Log out and back in for group changes to apply"
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
