#!/bin/bash
# Fine-tuning kolorów przy maksymalnej jasności

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Ustawienie maksymalnej jasności ==="
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800

echo -e "\n=== Test różnych korekcji kolorów (zmniejszenie zielonego) ==="

# TEST 1: Gamma reduction (zmniejsza zielony)
echo "1. Gamma 0.6..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    gamma gamma=0.6 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color1_gamma06.jpg 2>&1 | grep -v "Setting"

# TEST 2: Hue shift większy
echo "2. Hue shift 0.15..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.15 ! gamma gamma=0.65 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color2_hue15.jpg 2>&1 | grep -v "Setting"

# TEST 3: Hue + saturation
echo "3. Hue 0.2 + saturation 0.9..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.2 saturation=0.9 ! gamma gamma=0.65 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color3_hue20_sat09.jpg 2>&1 | grep -v "Setting"

# TEST 4: Contrast adjustment
echo "4. Hue 0.18 + contrast..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.18 saturation=0.92 contrast=1.05 ! \
    gamma gamma=0.63 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color4_contrast.jpg 2>&1 | grep -v "Setting"

# TEST 5: Conservative (subtelna korekta)
echo "5. Subtelna korekta..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.12 saturation=0.95 brightness=0.02 ! \
    gamma gamma=0.67 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color5_subtle.jpg 2>&1 | grep -v "Setting"

# TEST 6: Aggressive (mocna korekta)
echo "6. Mocna korekta..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videobalance hue=0.25 saturation=0.85 ! \
    gamma gamma=0.58 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color6_aggressive.jpg 2>&1 | grep -v "Setting"

# TEST 7: Format UYVY (może mieć lepsze kolory)
echo "7. Format UYVY..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=UYVY ! \
    videobalance hue=0.15 ! gamma gamma=0.65 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/color7_uyvy.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ 7 wersji zapisanych w: $TEST_DIR/"
ls -lh $TEST_DIR/color*.jpg
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
echo -e "\nWybierz która ma najlepsze kolory!"
