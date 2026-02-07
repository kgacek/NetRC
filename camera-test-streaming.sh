#!/bin/bash
# Test streamingu video dla car-client.py

CAMERA_DEV="/dev/video0"
TEST_DIR="camera_tests"
mkdir -p $TEST_DIR

echo "=== Optymalne ustawienia dla streamingu ==="
v4l2-ctl -d $CAMERA_DEV --set-ctrl=exposure=3200,gain=8000,analogue_gain=1800

echo -e "\n=== TEST 1: Stream 640x480 @ 30fps (docelowy dla WebRTC) ==="
timeout 5 gst-launch-1.0 -v v4l2src device=/dev/video0 ! \
    video/x-raw,width=640,height=480,framerate=30/1 ! \
    fpsdisplaysink video-sink=fakesink text-overlay=false 2>&1 | grep -E "fps|framerate"

echo -e "\n=== TEST 2: Zapis 5 sekund video ==="
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=150 ! \
    video/x-raw,width=640,height=480,framerate=30/1 ! \
    videoconvert ! x264enc tune=zerolatency speed-preset=ultrafast ! \
    mp4mux ! filesink location=$TEST_DIR/test_stream_5sec.mp4 2>&1 | tail -5

echo -e "\n=== TEST 3: WebRTC-like pipeline (VP8) ==="
timeout 3 gst-launch-1.0 v4l2src device=/dev/video0 ! \
    video/x-raw,width=640,height=480,framerate=30/1 ! \
    videoconvert ! vp8enc deadline=1 ! fakesink 2>&1 | grep -i "fps\|error" | tail -5

echo -e "\n=== TEST 4: Snapshot z różnych lighting conditions ==="
for gain in 4000 8000 12000 16000; do
    echo "Gain $gain..."
    v4l2-ctl -d $CAMERA_DEV --set-ctrl=gain=$gain
    sleep 0.2
    gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
        video/x-raw,width=640,height=480 ! videoconvert ! jpegenc quality=95 ! \
        filesink location=$TEST_DIR/gain_${gain}.jpg 2>&1 >/dev/null
done

echo -e "\n=== WYNIKI ==="
ls -lh $TEST_DIR/*.jpg $TEST_DIR/*.mp4 2>/dev/null
echo -e "\nPobierz: scp -r user@radxa:$TEST_DIR ."
