#!/bin/bash
# Próba konfiguracji ISP dla lepszego przetwarzania kolorów

echo "=== Konfiguracja media pipeline ISP ==="

# Resetuj do domyślnych formatów
echo "1. Reset formatów..."
media-ctl -r

# Skonfiguruj pipeline: Sensor -> CSI -> ISP -> Output
echo "2. Konfiguracja sensora (1640x1232)..."
media-ctl --set-v4l2 '"m00_b_imx219 2-0010":0[fmt:SRGGB10_1X10/1640x1232]'

echo "3. Konfiguracja CSI input..."
media-ctl --set-v4l2 '"rkisp-csi-subdev":0[fmt:SRGGB10_1X10/1640x1232]'

echo "4. Konfiguracja ISP input..."
media-ctl --set-v4l2 '"rkisp-isp-subdev":0[fmt:SRGGB10_1X10/1640x1232]'

echo "5. Konfiguracja ISP output (YUV)..."
media-ctl --set-v4l2 '"rkisp-isp-subdev":2[fmt:YUYV8_2X8/1640x1232]'

echo -e "\n=== Obecna konfiguracja pipeline ==="
media-ctl -p | grep -A 5 "m00_b_imx219"
media-ctl -p | grep -A 8 "rkisp-isp-subdev"

# Ustaw exposure/gain
CAMERA_DEV="/dev/video0"
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800

# Test
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo -e "\n=== Test z nową konfiguracją ISP ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/isp_reconfigured.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ $TEST_DIR/isp_reconfigured.jpg"
echo "Porównaj z max_raw.jpg"
