#!/bin/bash
# Test różnych pipeline GStreamer dla najlepszych kolorów

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

# Ustaw rozsądne wartości ekspozycji
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=2500
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=5000
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=1400
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo "=== Test różnych pipeline GStreamer ==="

echo "1. Podstawowy (bez korekcji)..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_basic.jpg 2>&1 | grep -v "Setting"

echo "2. Z videobalance..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videobalance ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_balance.jpg 2>&1 | grep -v "Setting"

echo "3. Z gamma correction..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    gamma gamma=0.8 ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_gamma08.jpg 2>&1 | grep -v "Setting"

echo "4. Z gamma=1.2..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    gamma gamma=1.2 ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_gamma12.jpg 2>&1 | grep -v "Setting"

echo "5. Balance + gamma 0.8..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videobalance ! gamma gamma=0.8 ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_bal_gam08.jpg 2>&1 | grep -v "Setting"

echo "6. Format NV12 (YUV)..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_nv12.jpg 2>&1 | grep -v "Setting"

echo "7. Format UYVY..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=UYVY ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/gst_uyvy.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== Gotowe! ==="
ls -lh $TEST_DIR/gst_*.jpg
echo -e "\nPobierz folder: scp -r user@radxa:$TEST_DIR ."
