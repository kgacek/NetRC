#!/bin/bash
# Porównanie jakości obrazu - znajdź optymalne ustawienia

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Test kombinacji exposure + gain dla najlepszej jakości ==="

combinations=(
    "2000 5000 1200"
    "2500 6000 1400"
    "3000 7000 1600"
    "3000 8000 1800"
    "3200 8000 1800"
    "3500 9000 2000"
    "3500 10000 2200"
    "4000 10000 2400"
    "4095 12000 2600"
)

idx=1
for combo in "${combinations[@]}"; do
    read -r exp gain again <<< "$combo"
    
    printf "\n[%d/%d] exposure=%d, gain=%d, analogue_gain=%d\n" \
        $idx ${#combinations[@]} $exp $gain $again
    
    v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=$exp,gain=$gain,analogue_gain=$again
    sleep 0.3
    
    gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
        video/x-raw,width=640,height=480 ! videoconvert ! jpegenc quality=95 ! \
        filesink location=$TEST_DIR/combo${idx}_e${exp}_g${gain}_a${again}.jpg 2>&1 >/dev/null
    
    ((idx++))
done

echo -e "\n=== Wszystkie testy ukończone ==="
ls -lh $TEST_DIR/combo*.jpg

echo -e "\n=== Porównaj zdjęcia i wybierz najlepsze ==="
echo "Pobierz: scp -r user@radxa:$TEST_DIR ."
echo ""
echo "Sprawdź pod kątem:"
echo "  - Jasność (nie za ciemne, nie przepalone)"
echo "  - Kolory (nie za zielone/żółte/niebieskie)"
echo "  - Szum (mniej = lepiej)"
echo "  - Ostrość"
