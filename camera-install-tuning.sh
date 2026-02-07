#!/bin/bash
# Pobieranie i instalacja ISP tuning files dla IMX219

echo "=== Instalacja narzędzi ==="
apt update
apt install -y git wget curl

echo -e "\n=== Tworzenie katalogu dla tuning files ==="
mkdir -p /etc/iqfiles
mkdir -p /tmp/isp_tuning

cd /tmp/isp_tuning

echo -e "\n=== Pobieranie tuning files z Rockchip SDK ==="

# Oficjalne repo Rockchip dla RK356x
echo "1. Próba: camera_engine_rkaiq..."
git clone --depth=1 https://github.com/rockchip-linux/camera_engine_rkaiq.git 2>&1 | tail -5

if [ -d camera_engine_rkaiq ]; then
    echo "   Szukanie IMX219 tuning files..."
    find camera_engine_rkaiq -name "*imx219*" -o -name "*IMX219*" | grep -i xml
    
    # Kopiuj znalezione pliki
    find camera_engine_rkaiq -name "*imx219*.xml" -exec cp {} /etc/iqfiles/ \; 2>/dev/null
fi

# Alternatywne źródło
echo -e "\n2. Próba: rkisp (alternative)..."
git clone --depth=1 https://github.com/rockchip-linux/rkisp.git 2>&1 | tail -5

if [ -d rkisp ]; then
    find rkisp -name "*imx219*" -o -name "*219*" | grep -i xml
    find rkisp -name "*.xml" -exec cp {} /etc/iqfiles/ \; 2>/dev/null
fi

# Jeśli nie ma IMX219, użyj generic lub innego sensora jako bazy
echo -e "\n3. Szukanie generic/fallback tuning files..."
find . -name "*.xml" 2>/dev/null | head -10

# Sprawdź co udało się pobrać
echo -e "\n=== Pobrane pliki ==="
ls -lh /etc/iqfiles/

if [ -z "$(ls -A /etc/iqfiles/)" ]; then
    echo -e "\n⚠ Nie znaleziono IMX219 tuning files w oficjalnych repo"
    echo "Tworzę podstawowy plik konfiguracyjny..."
    
    # Stwórz minimalny XML config
    cat > /etc/iqfiles/imx219.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<root>
  <sensor_name>IMX219</sensor_name>
  <auto_white_balance>
    <enable>1</enable>
    <mode>auto</mode>
  </auto_white_balance>
  <auto_exposure>
    <enable>1</enable>
    <mode>auto</mode>
  </auto_exposure>
  <gamma>
    <enable>1</enable>
    <value>2.2</value>
  </gamma>
</root>
XMLEOF
    
    echo "Utworzono podstawowy /etc/iqfiles/imx219.xml"
fi

echo -e "\n=== Sprawdzanie gdzie ISP szuka plików ==="
strings /sys/kernel/debug/rkisp/log 2>/dev/null | grep -i "iq\|xml\|tuning" | head -10

# Alternatywne lokalizacje
mkdir -p /vendor/etc/camera
mkdir -p /system/etc/camera
mkdir -p /usr/share/rkisp

# Linkuj do różnych lokalizacji
ln -sf /etc/iqfiles/* /vendor/etc/camera/ 2>/dev/null
ln -sf /etc/iqfiles/* /system/etc/camera/ 2>/dev/null
ln -sf /etc/iqfiles/* /usr/share/rkisp/ 2>/dev/null

echo -e "\n=== GOTOWE ==="
echo "Tuning files zainstalowane w:"
echo "  /etc/iqfiles/"
echo "  /vendor/etc/camera/"
echo "  /system/etc/camera/"
echo ""
echo "RESTART wymagany: reboot"
