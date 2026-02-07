#!/bin/bash
# Dodatkowa weryfikacja - porównanie RAW vs ISP

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Porównanie RAW (przed ISP) vs Processed (po ISP) ==="

v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=6,exposure=2000,gain=5000  # Color bar

echo -e "\n1. RAW output (video2 - bypass ISP)..."
v4l2-ctl -d /dev/video2 --set-fmt-video=width=1920,height=1080,pixelformat=RGGB
timeout 2 v4l2-ctl -d /dev/video2 --stream-mmap --stream-count=1 --stream-to=/tmp/raw.data 2>&1 | head -5
if [ -f /tmp/raw.data ] && [ -s /tmp/raw.data ]; then
    SIZE=$(stat -f%z /tmp/raw.data 2>/dev/null || stat -c%s /tmp/raw.data 2>/dev/null)
    echo "  ✓ RAW data captured (${SIZE} bytes - Bayer pattern)"
else
    echo "  (RAW capture może nie działać - to OK)"
fi

echo -e "\n2. ISP processed (video0 - przez ISP)..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/verify_isp_colorbar.jpg 2>&1 | grep -v "Setting"

# Przywróć normalny tryb
v4l2-ctl -d $CAMERA_DEV --set-ctrl=test_pattern=0,exposure=4095,gain=15000,analogue_gain=2800

echo -e "\n3. ISP debayering test (real image)..."
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/verify_isp_debayer.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST: Czy ISP wykonuje crop/zoom ==="
# Ustaw crop na ISP
media-ctl --set-selection '"rkisp-isp-subdev":0[crop:(100,100)/800x600]' 2>&1

gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! jpegenc ! \
    filesink location=$TEST_DIR/verify_isp_crop.jpg 2>&1 | grep -v "Setting"

# Reset crop
media-ctl -r 2>&1 >/dev/null

echo -e "\n✓ Testy zapisane w: $TEST_DIR/"
ls -lh $TEST_DIR/verify_*.jpg
echo -e "\nJeśli verify_isp_colorbar.jpg pokazuje kolorowe pasy,"
echo "to ISP DZIAŁA prawidłowo - brak tylko auto-white-balance tuning"
