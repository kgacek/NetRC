#!/bin/bash
# Sprawdzanie wszystkich kontrolek związanych z kolorem

CAMERA_DEV="/dev/video0"

echo "=== Wszystkie dostępne kontrolki kamery ==="
v4l2-ctl -d $CAMERA_DEV --list-ctrls-menus

echo -e "\n=== Szukanie kontrolek white balance ==="
v4l2-ctl -d $CAMERA_DEV --list-ctrls-menus | grep -i "white\|balance\|color\|hue\|saturation"

echo -e "\n=== Aktualne wartości wszystkich kontrolek ==="
v4l2-ctl -d $CAMERA_DEV --all
