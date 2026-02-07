#!/bin/bash
# Weryfikacja czy ISP działa hardware'owo (nie wymaga tuning files)

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== TEST 1: ISP skalowanie (dowód że ISP przetwarza) ==="

# Ustaw normalny obraz
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0,exposure=4095,gain=15000,analogue_gain=2800

# Różne rozdzielczości - ISP musi skalować
echo "640x480..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_scale_640x480.jpg 2>&1 | grep -v "Setting"

echo "1280x720..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=1280,height=720 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_scale_1280x720.jpg 2>&1 | grep -v "Setting"

echo "1920x1080..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=1920,height=1080 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_scale_1920x1080.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 2: Test pattern z kamery (weryfikacja ISP processing) ==="

# Color bars - ISP powinien pokazać czyste kolory jeśli działa
echo "Test pattern: Color Bar..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=6  # Color Bar

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_colorbar.jpg 2>&1 | grep -v "Setting"

# Solid colors
echo "Test pattern: Solid Red..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=3
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_red.jpg 2>&1 | grep -v "Setting"

echo "Test pattern: Solid Green..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=4
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_green.jpg 2>&1 | grep -v "Setting"

echo "Test pattern: Solid Blue..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=5
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_blue.jpg 2>&1 | grep -v "Setting"

echo "Test pattern: Solid White..."
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=2
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_white.jpg 2>&1 | grep -v "Setting"

# Przywróć normalny obraz
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0

echo -e "\n=== TEST 3: Konwersja formatów (ISP debayering) ==="

# ISP musi przekonwertować Bayer (SRGGB10) do YUV/RGB
echo "Format NV12..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_fmt_nv12.jpg 2>&1 | grep -v "Setting"

echo "Format UYVY..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=UYVY ! jpegenc ! \
    filesink location=$TEST_DIR/isp_fmt_uyvy.jpg 2>&1 | grep -v "Setting"

echo "Format YU12..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=YU12 ! jpegenc ! \
    filesink location=$TEST_DIR/isp_fmt_yu12.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 4: Statystyki ISP (video8) ==="
echo "Sprawdzanie czy ISP zbiera statystyki AE/AWB..."
timeout 2 cat /dev/video8 > /tmp/isp_stats.bin 2>&1 &
STATS_PID=$!
sleep 1

# Trigger capture
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=10 ! fakesink 2>&1 >/dev/null &
sleep 1

wait $STATS_PID 2>/dev/null
if [ -f /tmp/isp_stats.bin ] && [ -s /tmp/isp_stats.bin ]; then
    SIZE=$(stat -f%z /tmp/isp_stats.bin 2>/dev/null || stat -c%s /tmp/isp_stats.bin 2>/dev/null)
    echo "  ✓ ISP generuje statystyki! (${SIZE} bytes)"
    echo "  ISP DZIAŁA hardware'owo - brak tylko tuning files"
else
    echo "  ✗ Brak statystyk ISP - możliwy problem hardware"
fi
rm -f /tmp/isp_stats.bin

echo -e "\n=== WYNIK WERYFIKACJI ==="
echo "Sprawdź zdjęcia:"
echo "1. isp_colorbar.jpg - powinny być wyraźne kolorowe pasy"
echo "2. isp_red/green/blue.jpg - powinny być odpowiednie jednolite kolory"
echo "3. isp_scale_*.jpg - różne rozdzielczości (ISP skaluje)"
echo "4. Jeśli wszystko OK = ISP działa, brak tylko plików kalibracyjnych"
echo ""
ls -lh $TEST_DIR/isp_*.jpg
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
