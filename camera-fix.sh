#!/bin/bash
# Skrypt naprawy ustawień kamery dla Radxa Zero 3W

echo "=== Naprawianie ustawień kamery ==="

# Wyłącz auto-exposure i ustaw ręcznie
echo "1. Ustawianie exposure..."
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto=1  # Manual mode
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_absolute=500

# Zwiększ gain (wzmocnienie)
echo "2. Ustawianie gain..."
v4l2-ctl -d /dev/video0 --set-ctrl=gain=100

# Zwiększ brightness
echo "3. Ustawianie brightness..."
v4l2-ctl -d /dev/video0 --set-ctrl=brightness=50

# Ustaw contrast
echo "4. Ustawianie contrast..."
v4l2-ctl -d /dev/video0 --set-ctrl=contrast=32

# Włącz auto white balance
echo "5. Ustawianie white balance..."
v4l2-ctl -d /dev/video0 --set-ctrl=white_balance_automatic=1

echo -e "\n=== Obecne ustawienia po zmianach ==="
v4l2-ctl -d /dev/video0 --list-ctrls

echo -e "\n=== Test: robienie zdjęcia ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! filesink location=test_fixed.jpg

echo -e "\nZdjęcie zapisane jako test_fixed.jpg"
