#!/bin/bash
# Sprawdzanie kontrolek ISP (może mieć white balance)

echo "=== Kontrolki ISP params (video9) ==="
v4l2-ctl -d /dev/video9 --list-ctrls 2>&1 || echo "Brak kontrolek na video9"

echo -e "\n=== Kontrolki ISP subdev0 ==="
v4l2-ctl -d /dev/v4l-subdev0 --list-ctrls 2>&1 | head -50

echo -e "\n=== Kontrolki CSI subdev1 ==="
v4l2-ctl -d /dev/v4l-subdev1 --list-ctrls 2>&1 | head -30

echo -e "\n=== Szukanie white balance w całym systemie ==="
for dev in /dev/video* /dev/v4l-subdev*; do
    echo "Sprawdzam $dev:"
    v4l2-ctl -d $dev --list-ctrls 2>/dev/null | grep -i "white\|awb\|color_processing" && echo "  ^^^ Znaleziono kontrolki!" || echo "  (brak)"
done
