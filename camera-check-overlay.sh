#!/bin/bash
# Sprawdzanie device tree i overlayów

echo "=== 1. Sprawdzanie aktywnych overlayów ==="
if [ -f /boot/armbianEnv.txt ]; then
    echo "Overlays w /boot/armbianEnv.txt:"
    grep -i "overlay\|fdt" /boot/armbianEnv.txt
elif [ -f /boot/uEnv.txt ]; then
    echo "Overlays w /boot/uEnv.txt:"
    grep -i "overlay\|fdt" /boot/uEnv.txt
fi

echo -e "\n=== 2. Dostępne overlaye kamery ==="
find /boot/dtb /boot/dtbo -name "*imx219*" -o -name "*camera*" 2>/dev/null

echo -e "\n=== 3. Device tree - informacje o kamerze ==="
if [ -d /proc/device-tree ]; then
    find /proc/device-tree -name "*imx219*" -o -name "*camera*" 2>/dev/null | head -10
fi

echo -e "\n=== 4. Status i2c kamery ==="
i2cdetect -y 2 2>/dev/null || i2cdetect -y 0 2>/dev/null

echo -e "\n=== 5. Logi kernela o kamerze przy starcie ==="
dmesg | grep -i "imx219\|camera\|csi" | head -20

echo -e "\n=== 6. Moduły video ==="
lsmod | grep -i "video\|v4l2\|isp"

echo -e "\n=== 7. Restart pipeline i test ==="
# Kill wszystkie procesy używające kamery
killall gst-launch-1.0 2>/dev/null

# Restart media subsystem
media-ctl -r
sleep 1

# Podstawowy test
echo "Test podstawowy..."
v4l2-ctl -d /dev/video0 --set-fmt-video=width=640,height=480,pixelformat=NV12
v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=1 --stream-to=/tmp/test.raw 2>&1 | head -5

if [ -f /tmp/test.raw ] && [ -s /tmp/test.raw ]; then
    echo "✓ v4l2-ctl capture działa!"
else
    echo "✗ v4l2-ctl capture nie działa"
fi

echo -e "\n=== 8. Sprawdzanie czy urządzenie jest busy ==="
lsof /dev/video* 2>/dev/null || fuser /dev/video* 2>/dev/null
