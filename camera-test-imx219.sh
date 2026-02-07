#!/bin/bash
# Test różnych wartości exposure i gain dla IMX219

CAMERA_DEV="/dev/video0"

echo "=== Testowanie różnych kombinacji exposure i gain ==="

# Wyłącz test pattern
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

# Test różnych kombinacji
# Format: exposure gain analogue_gain
combinations=(
    "1575 2000 1000"
    "2000 3000 1200"
    "2500 5000 1500"
    "3000 8000 2000"
    "3500 10000 2500"
    "4000 15000 2800"
)

for combo in "${combinations[@]}"; do
    read -r exposure gain analogue_gain <<< "$combo"
    
    echo "Test: exposure=$exposure, gain=$gain, analogue_gain=$analogue_gain..."
    v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=$exposure
    v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=$gain
    v4l2-ctl -d $CAMERA_DEV --set-ctrl=analogue_gain=$analogue_gain
    
    # Poczekaj żeby sensor się dostosował
    sleep 0.3
    
    gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
        video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
        filesink location=test_e${exposure}_g${gain}_a${analogue_gain}.jpg 2>&1 | grep -v "Setting pipeline"
    
    echo "  ✓ test_e${exposure}_g${gain}_a${analogue_gain}.jpg"
done

echo -e "\n=== Gotowe! Sprawdź zdjęcia: ==="
ls -lh test_e*.jpg

echo -e "\nWybierz najlepszą kombinację i użyj tych wartości w car-client.py!"
