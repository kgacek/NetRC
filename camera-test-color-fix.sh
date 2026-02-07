#!/bin/bash
# Testy dla naprawy kolorów bez hardware white balance

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

# Ustaw rozsądne wartości (mniejszy gain = lepsze kolory)
echo "=== Konfiguracja kamery (zredukowany gain dla lepszych kolorów) ==="
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=2800
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=4000
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=1200
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo "Ustawione:"
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

echo -e "\n=== TEST 1: Format NV12 + gamma 0.6 (redukuje zielony) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.6 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color_nv12_g06.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 2: Format NV12 + gamma 0.7 ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.7 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color_nv12_g07.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 3: Format NV12 + gamma 0.8 ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.8 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color_nv12_g08.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 4: Gamma + videobalance (hue shift) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    gamma gamma=0.7 ! \
    videobalance hue=-0.2 saturation=1.1 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color_hue_shift.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 5: Manualna korekcja RGB (reduce green) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videobalance hue=0.15 saturation=0.9 ! \
    gamma gamma=0.75 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color_manual_fix.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 6: Format UYVY (inny color space) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=UYVY ! \
    gamma gamma=0.7 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color_uyvy.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ Testy zapisane w: $TEST_DIR/"
ls -lh $TEST_DIR/color_*.jpg
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
