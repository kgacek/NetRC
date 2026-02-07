#!/bin/bash
# Test różnych ustawień exposure dla znalezienia optymalnego

echo "=== Testowanie różnych wartości exposure ==="

# Ustaw manual exposure
v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto=1

# Test różnych wartości
for exposure in 100 250 500 1000 2000; do
    echo "Testowanie exposure=$exposure..."
    v4l2-ctl -d /dev/video0 --set-ctrl=exposure_absolute=$exposure
    v4l2-ctl -d /dev/video0 --set-ctrl=gain=150
    v4l2-ctl -d /dev/video0 --set-ctrl=brightness=50
    
    gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
        video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
        filesink location=test_exp_${exposure}.jpg
    
    echo "  -> test_exp_${exposure}.jpg"
done

echo -e "\nSprawdź zdjęcia i wybierz najlepsze ustawienie exposure"
ls -lh test_exp_*.jpg
