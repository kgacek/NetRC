#!/bin/bash
# Skrypt naprawy ustawień kamery dla Radxa Zero 3W z IMX219

echo "=== Naprawianie ustawień kamery IMX219 ==="

# Używamy /dev/video0 (działa równie dobrze jak subdev3)
CAMERA_DEV="/dev/video0"

echo "Obecne wartości (przed zmianą):"
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

# Zwiększ exposure (zakres: 0-4095, default=1575)
echo -e "\n1. Ustawianie exposure=2500..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=2500

# WAŻNE: Zwiększ gain (zakres: 256-43663, default=256 - MINIMUM!)
echo "2. Ustawianie gain=5000..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=5000

# Zwiększ analogue_gain (zakres: 256-2816, default=512)
echo "3. Ustawianie analogue_gain=1500..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=1500

# Wyłącz test pattern
echo "4. Wyłączanie test pattern..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo -e "\n=== Nowe wartości (po zmianie) ==="
v4l2-ctl -d $CAMERA_DEV --get-ctrl=exposure,gain,analogue_gain

echo -e "\n=== Test: robienie zdjęcia ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=test_fixed.jpg 2>&1 | grep -v "Setting pipeline"

echo -e "\n✓ Zdjęcie zapisane jako test_fixed.jpg"
echo "Sprawdź czy jest jaśniejsze!"
