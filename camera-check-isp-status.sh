#!/bin/bash
# Diagnostyka ISP Rockchip

echo "=== Sprawdzanie stanu ISP ==="

echo -e "\n1. Parametry ISP subdev0:"
media-ctl -p | grep -A 30 "rkisp-isp-subdev"

echo -e "\n2. Sprawdzanie czy ISP przetwarza dane:"
v4l2-ctl -d /dev/v4l-subdev0 --get-fmt-video

echo -e "\n3. Parametry video9 (ISP params):"
v4l2-ctl -d /dev/video9 --all 2>&1 | head -40

echo -e "\n4. Sprawdzanie plików kalibracyjnych ISP:"
find /system /vendor /etc /lib/firmware -name "*isp*" -o -name "*rkisp*" -o -name "*camera*" 2>/dev/null | grep -i "xml\|json\|bin\|tuning"

echo -e "\n5. Moduły kernela związane z ISP:"
lsmod | grep -i "isp\|camera\|video"

echo -e "\n6. Logi kernela o ISP:"
dmesg | grep -i "isp\|rkisp" | tail -30

echo -e "\n7. Sprawdzanie sysfs ISP:"
find /sys -name "*isp*" 2>/dev/null | head -20

echo -e "\n8. Procesy związane z ISP:"
ps aux | grep -i "isp\|camera" | grep -v grep
