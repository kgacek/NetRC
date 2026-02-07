#!/bin/bash
# Pełny restart kamery i video subsystem

echo "=== Zabijanie wszystkich procesów video ==="
killall -9 gst-launch-1.0 2>/dev/null
killall -9 v4l2-ctl 2>/dev/null
killall -9 ffmpeg 2>/dev/null
sleep 1

echo "=== Unbind/bind sensorów i ISP ==="

# Unbind IMX219
if [ -d /sys/bus/i2c/drivers/imx219/2-0010 ]; then
    echo "Unbinding IMX219..."
    echo 2-0010 > /sys/bus/i2c/drivers/imx219/unbind 2>/dev/null
fi

# Unbind ISP
if [ -d /sys/bus/platform/drivers/rkisp/fdff0000.rkisp ]; then
    echo "Unbinding ISP..."
    echo fdff0000.rkisp > /sys/bus/platform/drivers/rkisp/unbind 2>/dev/null
fi

# Unbind CSI
if [ -d /sys/bus/platform/drivers/rockchip-csi2-dphy/csi2-dphy0 ]; then
    echo "Unbinding CSI..."
    echo csi2-dphy0 > /sys/bus/platform/drivers/rockchip-csi2-dphy/unbind 2>/dev/null
fi

sleep 2

# Bind z powrotem
echo "Binding CSI..."
echo csi2-dphy0 > /sys/bus/platform/drivers/rockchip-csi2-dphy/bind 2>/dev/null

echo "Binding ISP..."
echo fdff0000.rkisp > /sys/bus/platform/drivers/rkisp/bind 2>/dev/null

echo "Binding IMX219..."
echo 2-0010 > /sys/bus/i2c/drivers/imx219/bind 2>/dev/null

sleep 3

echo -e "\n=== Status urządzeń ==="
ls -la /dev/video* 2>&1 | head -5

echo -e "\n=== Reset media controller ==="
media-ctl -r

echo -e "\n=== Test capture ==="
v4l2-ctl -d /dev/video0 --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800,test_pattern=0
sleep 0.5

TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/after_restart.jpg 2>&1 | tail -5

if [ -s $TEST_DIR/after_restart.jpg ]; then
    echo -e "\n✓ DZIAŁA! Kamera naprawiona"
    ls -lh $TEST_DIR/after_restart.jpg
else
    echo -e "\n✗ Nadal nie działa - potrzebny REBOOT"
    echo "Uruchom: reboot"
fi
