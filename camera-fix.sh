#!/bin/bash
# Skrypt naprawy ustawień kamery dla Radxa Zero 3W z IMX219

echo "=== Naprawianie ustawień kamery IMX219 ==="

# WAŻNE: IMX219 ma kontrolki w /dev/v4l-subdev3, nie w /dev/video0!
SENSOR_DEV="/dev/v4l-subdev3"

# Wyłącz auto-exposure i ustaw ręcznie
echo "1. Ustawianie exposure na sensorze..."
# Dla IMX219: exposure range to zazwyczaj 1-3448 (linie)
v4l2-ctl -d $SENSOR_DEV --set-ctrl=exposure=1000

# Zwiększ gain (wzmocnienie)
echo "2. Ustawianie gain na sensorze..."
# Dla IMX219: analogue_gain range zazwyczaj 0-232
v4l2-ctl -d $SENSOR_DEV --set-ctrl=analogue_gain=100

# Możliwe dodatkowe kontrolki
echo "3. Próba ustawienia digital gain..."
v4l2-ctl -d $SENSOR_DEV --set-ctrl=digital_gain=256 2>/dev/null || echo "  (digital_gain niedostępny)"

# Wyłącz test pattern jeśli włączony
echo "4. Wyłączanie test pattern..."
v4l2-ctl -d $SENSOR_DEV --set-ctrl=test_pattern=0 2>/dev/null || echo "  (test_pattern niedostępny)"

echo -e "\n=== Obecne ustawienia sensora ==="
v4l2-ctl -d $SENSOR_DEV --list-ctrls
v4l2-ctl -d $SENSOR_DEV --all

echo -e "\n=== Test: robienie zdjęcia ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=test_fixed.jpg

echo -e "\nZdjęcie zapisane jako test_fixed.jpg"
