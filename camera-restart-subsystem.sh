#!/bin/bash
# Restart całego video subsystem

echo "=== Hard reset video subsystem ==="

# Kill wszystkie procesy video
killall -9 gst-launch-1.0 2>/dev/null
killall -9 v4l2-ctl 2>/dev/null

# Unbind i bind ISP
echo "Unbinding ISP..."
echo fdff0000.rkisp > /sys/bus/platform/drivers/rkisp/unbind 2>/dev/null
sleep 1

echo "Binding ISP..."
echo fdff0000.rkisp > /sys/bus/platform/drivers/rkisp/bind 2>/dev/null
sleep 2

# Reset media controller
media-ctl -r
sleep 1

# Sprawdź czy urządzenia są dostępne
echo -e "\n=== Status po restarcie ==="
ls -la /dev/video* /dev/v4l-subdev*

echo -e "\n=== Test capture ==="
v4l2-ctl -d /dev/video0 --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800
v4l2-ctl -d /dev/video0 --set-fmt-video=width=640,height=480,pixelformat=NV12
v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=1 --stream-to=/tmp/test.raw 2>&1

if [ -f /tmp/test.raw ] && [ -s /tmp/test.raw ]; then
    SIZE=$(stat -c%s /tmp/test.raw)
    echo "✓ Capture działa! (${SIZE} bytes)"
    
    # Konwersja do JPEG
    ffmpeg -f rawvideo -pixel_format nv12 -video_size 640x480 -i /tmp/test.raw \
           -frames:v 1 camera_tests/restart_test.jpg -y 2>&1 | grep -i "frame\|error"
    
    if [ -s camera_tests/restart_test.jpg ]; then
        echo "✓ JPEG zapisany: camera_tests/restart_test.jpg"
    fi
else
    echo "✗ Capture nadal nie działa"
    echo "Problem może być z device tree overlay"
fi
