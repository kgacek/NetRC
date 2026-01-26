# RPi Car Camera Streaming via Cloudflare Calls

Prosta aplikacja do streamowania wideo z kamery Raspberry Pi Zero 2 W do przeglądarki przez Cloudflare Calls (WebRTC SFU).

## Wymagania

### Cloudflare Calls
1. Utwórz konto na Cloudflare
2. Przejdź do Calls API: https://dash.cloudflare.com/
3. Utwórz nową aplikację i zapisz:
   - App ID
   - App Secret

### Raspberry Pi Zero 2 W
- Raspberry Pi OS (64-bit zalecane)
- Kamera Pi Camera Module
- Python 3.9+

## Instalacja

### Na Raspberry Pi:

```bash
# Zainstaluj zależności systemowe
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev python3-picamera2
sudo apt-get install -y libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev libswscale-dev libopus-dev libvpx-dev pkg-config

# Zainstaluj pakiety Python
pip3 install -r requirements.txt

# Ustaw zmienne środowiskowe
export CF_APP_ID="your-cloudflare-app-id"
export CF_APP_SECRET="your-cloudflare-app-secret"
```

## Użycie

### 1. Uruchom na Raspberry Pi:

```bash
python3 car-client.py
```

Aplikacja wyświetli **Session ID** - skopiuj go!

### 2. Otwórz w przeglądarce:

Otwórz `index.html` w przeglądarce i:
1. Wpisz **App ID**
2. Wpisz **App Secret**
3. Wpisz **Session ID** z RPi
4. Kliknij **Connect**

## Architektura

