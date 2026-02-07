#!/bin/bash
# Test raw vs ISP processed - porównanie

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Maksymalna jasność dla wszystkich testów ==="
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=4095,gain=15000,analogue_gain=2800

echo -e "\n=== TEST 1: ISP mainpath (video0) - default format ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/isp_mainpath_default.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 2: ISP mainpath - format NV12 ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/isp_mainpath_nv12.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 3: ISP mainpath - format UYVY ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=UYVY ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/isp_mainpath_uyvy.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 4: ISP selfpath (video1) ==="
gst-launch-1.0 v4l2src device=/dev/video1 num-buffers=1 ! \
    video/x-raw,width=640,height=480 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/isp_selfpath.jpg 2>&1 | grep -v "Setting"

echo -e "\n=== TEST 5: RAW writer (video2 - bypass ISP?) ==="
v4l2-ctl -d /dev/video2 --set-fmt-video=width=640,height=480 2>&1
timeout 2 gst-launch-1.0 v4l2src device=/dev/video2 num-buffers=1 ! \
    videoconvert ! jpegenc quality=95 ! \
    filesink location=$TEST_DIR/raw_video2.jpg 2>&1 | grep -v "Setting" || echo "  (może nie działać)"

echo -e "\n=== TEST 6: Bez videoconvert (mniej konwersji) ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
    video/x-raw,width=640,height=480,format=NV12 ! \
    jpegenc quality=95 ! \
    filesink location=$TEST_DIR/isp_no_convert.jpg 2>&1 | grep -v "Setting"

echo -e "\n✓ Testy zapisane w: $TEST_DIR/"
ls -lh $TEST_DIR/isp_*.jpg $TEST_DIR/raw_*.jpg 2>/dev/null
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
