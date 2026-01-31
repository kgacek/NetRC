#!/bin/bash
# DietPi Setup Script for car_client.py on Raspberry Pi Zero 2 W
# This script sets up the environment for streaming video from Pi Camera to Cloudflare

set -e

echo "=================================="
echo "Car Client Setup for DietPi"
echo "Raspberry Pi Zero 2 W"
echo "=================================="

# Update system
echo "Updating system packages..."
sudo apt update
sudo apt upgrade -y

# Install required system packages
echo "Installing system dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    libopus-dev \
    libvpx-dev \
    libsrtp2-dev \
    pkg-config \
    git \
    build-essential \
    cmake

# Install Pi Camera libraries
echo "Installing picamera2 dependencies..."
sudo apt install -y \
    python3-picamera2 \
    python3-libcamera \
    python3-kms++ \
    libcamera-dev

# Add dietpi user to video group for camera access
echo "Adding dietpi user to video group..."
sudo usermod -a -G video dietpi

# Enable camera interface
echo "Enabling camera interface..."
# Detect correct config.txt location
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_FILE="/boot/config.txt"
else
    echo "ERROR: Could not find config.txt"
    exit 1
fi

echo "Using config file: $CONFIG_FILE"

# Remove conflicting settings
echo "Removing any conflicting camera settings..."
sudo sed -i '/^camera_auto_detect=/d' "$CONFIG_FILE"
sudo sed -i '/^dtoverlay=ov5647/d' "$CONFIG_FILE"
sudo sed -i '/^dtoverlay=imx219/d' "$CONFIG_FILE"

# Enable legacy camera support for OV5647 (v1.3)
if ! grep -q "^start_x=1" "$CONFIG_FILE"; then
    echo "start_x=1" | sudo tee -a "$CONFIG_FILE"
fi

# Add OV5647 overlay explicitly
echo "dtoverlay=ov5647" | sudo tee -a "$CONFIG_FILE"

# Set GPU memory
if ! grep -q "^gpu_mem=" "$CONFIG_FILE"; then
    echo "gpu_mem=128" | sudo tee -a "$CONFIG_FILE"
else
    sudo sed -i 's/^gpu_mem=.*/gpu_mem=128/' "$CONFIG_FILE"
fi

# Verify camera hardware
echo "Checking for camera hardware..."
CAMERA_STATUS=$(vcgencmd get_camera 2>&1 || echo "supported=0 detected=0")
echo "Camera status: $CAMERA_STATUS"

if echo "$CAMERA_STATUS" | grep -q "detected=0"; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "WARNING: Camera NOT detected!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    echo "Common issues:"
    echo "  1. Camera cable not fully inserted (check both ends)"
    echo "  2. Camera connector plastic lock not closed"
    echo "  3. Cable inserted backwards (blue side faces USB ports)"
    echo "  4. Using DISPLAY port instead of CAMERA port"
    echo "  5. Defective camera module or cable"
    echo ""
    echo "To fix:"
    echo "  - Power off the Pi completely"
    echo "  - Remove and reinsert camera cable firmly"
    echo "  - Ensure blue/contact side faces USB ports"
    echo "  - Close the connector lock"
    echo "  - Power on and reboot"
    echo ""
fi

# Create virtual environment
echo "Creating Python virtual environment..."
cd /home/dietpi
if [ ! -d "car-env" ]; then
    python3 -m venv car-env
fi

# Activate virtual environment
source car-env/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install Python packages
echo "Installing Python dependencies..."
pip install \
    aiortc>=1.6.0 \
    aiohttp>=3.9.0 \
    av>=10.0.0 \
    numpy>=1.24.0

# Note: picamera2 is already installed system-wide, link it to venv
echo "Linking system picamera2 to virtual environment..."
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ln -sf /usr/lib/python3/dist-packages/picamera2* car-env/lib/python${PYTHON_VERSION}/site-packages/ 2>/dev/null || true
ln -sf /usr/lib/python3/dist-packages/libcamera* car-env/lib/python${PYTHON_VERSION}/site-packages/ 2>/dev/null || true

# Create environment file template
echo "Creating environment configuration template..."
cat > /home/dietpi/car-client.env << 'EOF'
# Cloudflare Calls Configuration
export CF_REALTIME_APP_ID="your-app-id"
export CF_REALTIME_TOKEN="your-app-secret"

# Signaling Server (optional)
export SIGNALING_SERVER="https://your-server.example.com"
EOF

# Create run script
echo "Creating run script..."
cat > /home/dietpi/run-car-client.sh << 'EOF'
#!/bin/bash
# Load environment variables
source /home/dietpi/car-client.env

# Activate virtual environment
source /home/dietpi/car-env/bin/activate

# Run the car client
python3 /home/dietpi/NetRC/car-client.py
EOF

chmod +x /home/dietpi/run-car-client.sh

# Create systemd service
echo "Creating systemd service..."
sudo tee /etc/systemd/system/car-client.service > /dev/null << 'EOF'
[Unit]
Description=Car Client WebRTC Streaming
After=network.target

[Service]
Type=simple
User=dietpi
WorkingDirectory=/home/dietpi/NetRC
EnvironmentFile=/home/dietpi/car-client.env
ExecStart=/home/dietpi/car-env/bin/python3 /home/dietpi/NetRC/car-client.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Set permissions
sudo chown -R dietpi:dietpi /home/dietpi/car-env
sudo chown dietpi:dietpi /home/dietpi/car-client.env
sudo chown dietpi:dietpi /home/dietpi/run-car-client.sh

echo ""
echo "=================================="
echo "Setup Complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Edit /home/dietpi/car-client.env with your Cloudflare credentials:"
echo "   nano /home/dietpi/car-client.env"
echo ""
echo "2. Clone or copy the NetRC repository to /home/dietpi/NetRC"
echo "   cd /home/dietpi"
echo "   git clone <your-repo-url> NetRC"
echo ""
echo "3. REBOOT to apply camera and permission settings:"
echo "   sudo reboot"
echo ""
echo "4. After reboot, verify camera is detected:"
echo "   vcgencmd get_camera"
echo "   # Should show: supported=1 detected=1"
echo ""
echo "   If camera NOT detected, debug with:"
echo "   libcamera-hello --list-cameras"
echo "   sudo i2cdetect -y 0"
echo "   sudo i2cdetect -y 1"
echo "   dmesg | grep -i camera"
echo "   ls -la /dev/video*"
echo "   cat /boot/firmware/config.txt | grep -E 'camera|gpu_mem|start_x'"
echo ""
echo "5. Test the camera:"
echo "   libcamera-hello"
echo ""
echo "6. Run manually:"
echo "   ./run-car-client.sh"
echo ""
echo "7. Or enable as service:"
echo "   sudo systemctl enable car-client"
echo "   sudo systemctl start car-client"
echo "   sudo systemctl status car-client"
echo ""
echo "8. View logs:"
echo "   sudo journalctl -u car-client -f"
echo ""
echo "=================================="
