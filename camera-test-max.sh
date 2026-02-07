#!/bin/bash
# Szybki test - maksymalne wartości dla najjaśniejszego obrazu

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Test maksymalnych wartości (najbardziej jasny obraz) ==="

v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=20000
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=2816
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo "Wartości:"
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

sleep 0.3

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/test_max_brightness.jpg 2>&1 | grep -v "Setting pipeline"

echo -e "\n✓ $TEST_DIR/test_max_brightness.jpg"
echo "Pobierz folder: scp -r user@radxa:$TEST_DIR ."
