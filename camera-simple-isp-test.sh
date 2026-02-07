#!/bin/bash
# Prosty test - czy ISP działa bez zmiany test_pattern

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

#echo "=== Restart kamery (reset state) ==="
# Reset media pipeline
#media-ctl -r 2>/dev/null
#sleep 0.5

# Upewnij się że test_pattern jest wyłączony
#v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0 2>/dev/null
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800

echo -e "\n=== TEST 1: Normalne zdjęcie (sprawdzenie czy działa) ==="
gst-launch-1.0 -v v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/test_normal.jpg 2>&1 | tail -10

if [ -s $TEST_DIR/test_normal.jpg ]; then
    echo "✓ Normalne zdjęcie OK"
else
    echo "✗ Problem z podstawowym pipeline"
    exit 1
fi

echo -e "\n=== TEST 2: Różne rozdzielczości (ISP scaling) ==="

echo "320x240..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=320,height=240 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/scale_320x240.jpg 2>&1 >/dev/null

echo "800x600..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=800,height=600 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/scale_800x600.jpg 2>&1 >/dev/null

echo "1280x720..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=1280,height=720 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/scale_1280x720.jpg 2>&1 >/dev/null

echo -e "\n=== TEST 3: Format NV12 (ISP format conversion) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! videoconvert ! jpegenc ! \
    filesink location=$TEST_DIR/format_nv12.jpg 2>&1 >/dev/null

echo -e "\n=== TEST 4: Statystyki ISP ==="
# Sprawdź czy video8 (statistics) otrzymuje dane
timeout 1 cat /dev/video8 > /tmp/isp_stats.bin 2>/dev/null &
STATS_PID=$!

# Trigger capture podczas czytania statystyk
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=5 ! fakesink 2>&1 >/dev/null

wait $STATS_PID 2>/dev/null
if [ -f /tmp/isp_stats.bin ] && [ -s /tmp/isp_stats.bin ]; then
    SIZE=$(stat -c%s /tmp/isp_stats.bin 2>/dev/null)
    echo "✓ ISP generuje statystyki (${SIZE} bytes)"
else
    echo "✗ Brak statystyk ISP"
fi

echo -e "\n=== WYNIKI ==="
ls -lh $TEST_DIR/test_*.jpg $TEST_DIR/scale_*.jpg $TEST_DIR/format_*.jpg 2>/dev/null

if [ -s $TEST_DIR/scale_320x240.jpg ] && [ -s $TEST_DIR/scale_1280x720.jpg ]; then
    echo -e "\n✓ ISP DZIAŁA - wykonuje skalowanie i konwersję formatów"
    echo "Brak tylko plików tuning dla auto white balance"
else
    echo -e "\n✗ Problem z ISP lub pipeline"
fi

echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
