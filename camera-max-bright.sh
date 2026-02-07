#!/bin/bash
# Szybki test - najjaśniejsza możliwa konfiguracja

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== MAKSYMALNA JASNOŚĆ ==="
echo "exposure=4095, gain=15000, analogue_gain=2800"

v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=15000
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=2800
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo -e "\nObecne wartości:"
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

echo -e "\n=== TEST 1: Bez korekcji kolorów ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/max_raw.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 2: Z gamma 0.65 ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.65 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/max_gamma65.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 3: Z gamma + balance ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.1 saturation=0.95 brightness=0.03 ! \
    gamma gamma=0.65 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/max_balanced.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ Zapisano w: $TEST_DIR/"
ls -lh $TEST_DIR/max_*.jpg
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
