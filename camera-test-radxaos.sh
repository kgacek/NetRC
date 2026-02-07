#!/bin/bash
# Test aktualnego stanu kamery na RadxaOS

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== 1. Sprawdzanie ISP tuning files ==="
find /etc /vendor /system /usr -name "*.xml" 2>/dev/null | grep -i "isp\|camera\|imx219" | head -10

echo -e "\n=== 2. Obecne ustawienia kamery ==="
v4l2-ctl -d $CAMERA_DEV --all | grep -A 30 "User Controls"

echo -e "\n=== 3. Test z domyślnymi ustawieniami ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/radxaos_default.jpg 2>&1 >/dev/null

echo -e "\n=== 4. Test z różnymi exposure/gain ==="

# Auto exposure (jeśli dostępne)
echo "Test 1: Niskie wartości..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=1000,gain=2000,analogue_gain=800
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/radxaos_low.jpg 2>&1 >/dev/null

echo "Test 2: Średnie wartości..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=2500,gain=6000,analogue_gain=1500
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/radxaos_medium.jpg 2>&1 >/dev/null

echo "Test 3: Wysokie wartości..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=12000,analogue_gain=2400
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/radxaos_high.jpg 2>&1 >/dev/null

echo -e "\n=== 5. Test różnych formatów ==="
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=3000,gain=8000,analogue_gain=1800

echo "NV12..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/radxaos_nv12.jpg 2>&1 >/dev/null

echo "UYVY..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=UYVY ! videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/radxaos_uyvy.jpg 2>&1 >/dev/null

echo -e "\n=== 6. Test FPS różnych rozdzielczości ==="
for res in "640x480" "1280x720" "1920x1080"; do
    echo "Testowanie $res..."
    timeout 3 gst-launch-1.0 v4l2src device=/dev/video0 ! \
        video/x-raw,width=${res%x*},height=${res#*x} ! \
        fpsdisplaysink video-sink=fakesink text-overlay=false 2>&1 | grep -i "fps" | tail -1
done

echo -e "\n=== WYNIKI ==="
ls -lh $TEST_DIR/radxaos_*.jpg
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
echo "Sprawdź które zdjęcie ma najlepszą jakość!"
