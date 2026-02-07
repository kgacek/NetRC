#!/bin/bash
# Test z wyższą jasnością i różnymi korektami kolorów

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Zwiększone wartości dla większej jasności ==="

# COMBO 1: Wysoka exposure, średni gain
echo -e "\n--- COMBO 1: High exposure, medium gain ---"
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=3800,gain=8000,analogue_gain=2200
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.65 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c1_basic.jpg 2>&1 | grep -v "Setting"

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.1 saturation=1.0 ! gamma gamma=0.65 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c1_balanced.jpg 2>&1 | grep -v "Setting"

# COMBO 2: Bardzo wysoka exposure, niski gain (mniej szumu)
echo -e "\n--- COMBO 2: Very high exposure, lower gain ---"
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=6000,analogue_gain=2000
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.7 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c2_basic.jpg 2>&1 | grep -v "Setting"

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.05 ! gamma gamma=0.7 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c2_balanced.jpg 2>&1 | grep -v "Setting"

# COMBO 3: Maksymalna jasność
echo -e "\n--- COMBO 3: Maximum brightness ---"
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=12000,analogue_gain=2600
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.65 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c3_max.jpg 2>&1 | grep -v "Setting"

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.08 saturation=0.95 ! gamma gamma=0.6 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c3_balanced.jpg 2>&1 | grep -v "Setting"

# COMBO 4: Zbalansowany (jasność + kolory)
echo -e "\n--- COMBO 4: Balanced (recommended) ---"
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=3500,gain=10000,analogue_gain=2400
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.12 saturation=1.0 brightness=0.05 ! \
    gamma gamma=0.68 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/bright_c4_recommended.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ Wszystkie testy zapisane w: $TEST_DIR/"
ls -lh $TEST_DIR/bright_*.jpg
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
echo -e "\nSprawdź które jest najjaśniejsze i ma najlepsze kolory!"
