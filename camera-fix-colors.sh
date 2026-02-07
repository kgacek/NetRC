#!/bin/bash
# Naprawa kolorów - zmniejszenie gain i test white balance

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Naprawa kolorów - rozsądne wartości ==="

# Zmniejsz wartości (max był za wysoki - dużo szumu i złe kolory)
# Ustawienia: średnia jasność, mniejszy szum
echo "1. Ustawianie exposure=2000..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=2000

echo "2. Ustawianie gain=4000..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=4000

echo "3. Ustawianie analogue_gain=1200..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=1200

# Wyłącz test pattern
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo -e "\n=== Obecne wartości ==="
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

echo -e "\n=== Test 1: Bez zmian white balance ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/test_nowhitebalance.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== Test 2: Z auto white balance w GStreamer ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videobalance ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/test_autobalance.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== Test 3: Z korektą kolorów ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videobalance saturation=1.2 ! \
    gamma gamma=1.2 ! \
    videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/test_colorcorrect.jpg 2>&1 | grep -v "Setting"

echo -e "\nZdjęcia zapisane w: $TEST_DIR/"
ls -lh $TEST_DIR/test_*.jpg

echo -e "\nPobierz folder: scp -r user@radxa:$TEST_DIR ."
