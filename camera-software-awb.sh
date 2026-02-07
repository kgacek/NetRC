#!/bin/bash
# Test software white balance w GStreamer

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800

echo "=== Software White Balance w GStreamer ==="

# Test 1: videobalance auto
echo "1. videobalance (auto)..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=30 ! \
    video/x-raw,width=640,height=480 ! \
    videobalance ! \
    videorate ! video/x-raw,framerate=1/1 ! \
    jpegenc ! filesink location=$TEST_DIR/swawb_auto.jpg 2>&1 >/dev/null

# Test 2: videobalance z adjustment
echo "2. videobalance + adjustment..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videobalance hue=0.15 saturation=0.95 ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/swawb_adjusted.jpg 2>&1 >/dev/null

# Test 3: autovideoconvert (może mieć AWB)
echo "3. autovideoconvert..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    autovideoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/swawb_autoconvert.jpg 2>&1 >/dev/null

# Test 4: whitebalance plugin (jeśli dostępny)
echo "4. Próba whitebalance plugin..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    whitebalance ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/swawb_plugin.jpg 2>&1 >/dev/null || echo "   (plugin niedostępny)"

# Test 5: opencv white balance (jeśli zainstalowane)
echo "5. Próba z opencv..."
if command -v python3 &> /dev/null; then
    python3 << 'EOF'
import cv2
import numpy as np
import subprocess

# Capture frame
subprocess.run(['v4l2-ctl', '-d', '/dev/video0', '--set-fmt-video=width=640,height=480,pixelformat=NV12'])
subprocess.run(['v4l2-ctl', '-d', '/dev/video0', '--stream-mmap', '--stream-count=1', '--stream-to=/tmp/raw.nv12'])

# Konwersja NV12 do BGR
cap = cv2.VideoCapture('/dev/video0')
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
ret, frame = cap.read()

if ret:
    # Simple white balance
    result = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    avg_a = np.average(result[:, :, 1])
    avg_b = np.average(result[:, :, 2])
    result[:, :, 1] = result[:, :, 1] - ((avg_a - 128) * (result[:, :, 0] / 255.0) * 1.1)
    result[:, :, 2] = result[:, :, 2] - ((avg_b - 128) * (result[:, :, 0] / 255.0) * 1.1)
    result = cv2.cvtColor(result, cv2.COLOR_LAB2BGR)
    cv2.imwrite('camera_tests/swawb_opencv.jpg', result)
    print("   ✓ OpenCV white balance OK")
else:
    print("   ✗ OpenCV capture failed")

cap.release()
EOF
else
    echo "   (python3 niedostępny)"
fi

echo -e "\n=== WYNIKI ==="
ls -lh $TEST_DIR/swawb_*.jpg 2>/dev/null

echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
echo "Porównaj z max_raw.jpg - sprawdź które ma lepsze kolory"
