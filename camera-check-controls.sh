#!/bin/bash
# Sprawdzanie gdzie są kontrolki kamery

echo "=== Kontrolki na /dev/video0 (mainpath - ISP output) ==="
v4l2-ctl -d /dev/video0 --list-ctrls

echo -e "\n=== Kontrolki na /dev/v4l-subdev0 (ISP) ==="
v4l2-ctl -d /dev/v4l-subdev0 --list-ctrls

echo -e "\n=== Kontrolki na /dev/v4l-subdev3 (IMX219 Sensor) ==="
v4l2-ctl -d /dev/v4l-subdev3 --list-ctrls

echo -e "\n=== Formaty na video0 ==="
v4l2-ctl -d /dev/video0 --list-formats-ext

echo -e "\n=== Formaty na subdev3 (sensor) ==="
v4l2-ctl -d /dev/v4l-subdev3 --list-formats-ext
