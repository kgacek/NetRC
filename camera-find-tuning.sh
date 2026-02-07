#!/bin/bash
# Sprawdzanie i instalacja ISP tuning files

echo "=== 1. Szukanie istniejących tuning files ==="
find /etc /usr/share /lib /opt -name "*.xml" -o -name "*.json" 2>/dev/null | grep -i "isp\|camera\|imx219\|rkisp"

echo -e "\n=== 2. Sprawdzanie dostępnych pakietów camera ==="
apt search camera 2>/dev/null | grep -i "rockchip\|rk35\|isp\|rkisp" | head -20

echo -e "\n=== 3. Sprawdzanie czy są zainstalowane pakiety ISP ==="
dpkg -l | grep -i "camera\|isp\|rockchip" | grep -v "lib\|dev"

echo -e "\n=== 4. Dostępne pakiety gstreamer-rockchip ==="
apt search gstreamer 2>/dev/null | grep -i "rockchip\|rk"

echo -e "\n=== 5. Kernel config dla ISP ==="
if [ -f /boot/config-$(uname -r) ]; then
    grep -i "ISP\|RKISP" /boot/config-$(uname -r)
elif [ -f /proc/config.gz ]; then
    zcat /proc/config.gz | grep -i "ISP\|RKISP"
fi

echo -e "\n=== REKOMENDACJE ==="
echo "Próby naprawy kolorów:"
echo "1. Zainstaluj rockchip-specific packages (jeśli dostępne)"
echo "2. Użyj software white balance w GStreamer"
echo "3. Pobierz tuning files z Rockchip SDK"
