#!/bin/bash
# Alternatywna metoda z auto-exposure

echo "=== Włączanie auto-exposure ==="

# Ustaw auto-exposure na aperture priority
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto=3  # Aperture Priority

# Ustaw wyższy target brightness dla auto-exposure
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto_priority=1

# Zwiększ brightness
v4l2-ctl -d /dev/video0 --set-ctrl=brightness=100

# Zwiększ gain
v4l2-ctl -d /dev/video0 --set-ctrl=gain=150

# Ustaw saturation
v4l2-ctl -d /dev/video0 --set-ctrl=saturation=64

echo -e "\n=== Test z auto-exposure ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! filesink location=test_auto.jpg

echo "Zdjęcie zapisane jako test_auto.jpg"
