#!/bin/bash
# Konfiguracja media pipeline dla optymalnej jakości

echo "=== Konfiguracja media pipeline ==="

# Sprawdź aktualną konfigurację formatu na sensorze
echo "Aktualna konfiguracja sensora:"
media-ctl -p | grep -A 10 "m00_b_imx219"

# Ustaw format na sensorze (opcjonalnie - zmniejsz rozdzielczość dla lepszego framerate)
echo -e "\nUstawianie formatu na sensorze (1640x1232 @ 30fps)..."
media-ctl --set-v4l2 '"m00_b_imx219 2-0010":0[fmt:SRGGB10_1X10/1640x1232]'

# Ustaw format na ISP input
echo "Ustawianie formatu na ISP input..."
media-ctl --set-v4l2 '"rkisp-isp-subdev":0[fmt:SRGGB10_1X10/1640x1232]'

# Ustaw format na ISP output
echo "Ustawianie formatu na ISP output..."
media-ctl --set-v4l2 '"rkisp-isp-subdev":2[fmt:YUYV8_2X8/1640x1232]'

# Teraz ustaw exposure i gain na sensorze
SENSOR_DEV="/dev/v4l-subdev3"

echo -e "\nUstawianie exposure i gain..."
v4l2-ctl -d $SENSOR_DEV --set-ctrl=exposure=1500
v4l2-ctl -d $SENSOR_DEV --set-ctrl=analogue_gain=150

echo -e "\n=== Test z nową konfiguracją ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
    filesink location=test_configured.jpg

echo "Zdjęcie zapisane jako test_configured.jpg"

# Pokaż aktualną konfigurację
echo -e "\n=== Aktualna konfiguracja po zmianach ==="
v4l2-ctl -d $SENSOR_DEV --all | grep -E "(exposure|gain)"
