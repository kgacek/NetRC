#!/bin/bash
# Sprawdzanie i instalacja potrzebnych narzędzi

echo "=== Sprawdzanie narzędzi ==="

# Sprawdź czy v4l2-ctl jest zainstalowany
if ! command -v v4l2-ctl &> /dev/null; then
    echo "Instalowanie v4l-utils..."
    sudo apt update
    sudo apt install -y v4l-utils
fi

# Sprawdź czy gstreamer jest zainstalowany
if ! command -v gst-launch-1.0 &> /dev/null; then
    echo "Instalowanie GStreamer..."
    sudo apt install -y gstreamer1.0-tools gstreamer1.0-plugins-base \
                        gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
fi

# Sprawdź media-ctl (dla konfiguracji ISP)
if ! command -v media-ctl &> /dev/null; then
    echo "media-ctl powinien być w v4l-utils..."
fi

echo -e "\n=== Sprawdzanie topologii media ==="
media-ctl -p

echo -e "\n=== Sprawdzanie urządzeń video ==="
ls -la /dev/video*

echo -e "\n=== Informacje o module kamery ==="
dmesg | grep -i camera
dmesg | grep -i v4l2

echo -e "\nGotowe! Możesz teraz uruchomić skrypty naprawcze."
