#!/bin/bash
# Test różnych wartości exposure dla IMX219

SENSOR_DEV="/dev/v4l-subdev3"

echo "=== Testowanie różnych wartości exposure na IMX219 ==="

# Wyłącz test pattern
v4l2-ctl -d $SENSOR_DEV --set-ctrl=test_pattern=0 2>/dev/null

# Test różnych kombinacji exposure i gain
echo "Testowanie kombinacji exposure i gain..."

# Format: exposure gain
combinations=(
    "100 50"
    "200 100"
    "500 100"
    "1000 100"
    "1500 150"
    "2000 150"
    "2000 200"
    "3000 200"
)

for combo in "${combinations[@]}"; do
    read -r exposure gain <<< "$combo"
    
    echo "Testowanie exposure=$exposure, gain=$gain..."
    v4l2-ctl -d $SENSOR_DEV --set-ctrl=exposure=$exposure
    v4l2-ctl -d $SENSOR_DEV --set-ctrl=analogue_gain=$gain
    
    # Poczekaj chwilę żeby sensor się dostosował
    sleep 0.5
    
    gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
        video/x-raw,width=640,height=480 ! videoconvert ! jpegenc ! \
        filesink location=test_e${exposure}_g${gain}.jpg 2>&1 | grep -v "Setting pipeline"
    
    echo "  -> test_e${exposure}_g${gain}.jpg"
done

echo -e "\nGotowe! Sprawdź zdjęcia:"
ls -lh test_e*.jpg
