#!/bin/bash
# Najlepsza konfiguracja - optymalna jasność i kolory

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Optymalna konfiguracja kamery ==="

# Wartości zbalansowane: jasno ale bez przesady (mniej szumu)
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=2200
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=6000
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=1500
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo "Ustawione wartości:"
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

echo -e "\n=== Pipeline z korektą gamma (zmniejsza zielonkawy odcień) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    gamma gamma=0.75 ! \
    videoconvert ! jpegenc quality=90 ! \
    filesink location=$TEST_DIR/test_optimal.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ $TEST_DIR/test_optimal.jpg"
echo -e "\nPobierz folder: scp -r user@radxa:$TEST_DIR ."
echo -e "\nJeśli kolory nadal są złe, uruchom:"
echo "  ./camera-check-color.sh  - sprawdź dostępne kontrolki white balance"
echo "  ./camera-test-gstreamer.sh  - przetestuj różne pipeline"
