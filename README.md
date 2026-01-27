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

### Serwer z nginx (dla signaling servera)
- Python 3.9+
- Nginx (do proxy signaling servera)

## Instalacja

### 1. Na serwerze z nginx - uruchom signaling server:

```bash
# Przenieś plik na serwer
scp signaling-server.py user@79-76-127-159.nip.io:~/

# Zaloguj się na serwer
ssh user@79-76-127-159.nip.io

# Uruchom signaling server
python3 signaling-server.py

# Lub jako service (w tle)
nohup python3 signaling-server.py > signaling.log 2>&1 &
```

### 2. Konfiguracja nginx (na serwerze):

Dodaj do nginx config:
```nginx
# /etc/nginx/sites-available/signaling
server {
    listen 8080;
    server_name 79-76-127-159.nip.io;

    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        
        # CORS headers
        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'Content-Type' always;
    }
}
```

Aktywuj:
```bash
sudo ln -s /etc/nginx/sites-available/signaling /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 3. Na Raspberry Pi:

```bash
# Zainstaluj zależności systemowe
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev python3-full python3-venv
sudo apt-get install -y libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev libswscale-dev libswresample-dev
sudo apt-get install -y libopus-dev libvpx-dev pkg-config
sudo apt-get install -y python3-picamera2 python3-numpy

# Utwórz i aktywuj virtual environment
cd ~/NetRC
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Zainstaluj pakiety Python w venv
pip install --upgrade pip
pip install -r requirements.txt

# Ustaw zmienne środowiskowe
export CF_REALTIME_APP_ID="your-cloudflare-app-id"
export CF_REALTIME_TOKEN="your-cloudflare-app-secret"
export SIGNALING_SERVER="http://79-76-127-159.nip.io:8080"
```

## Użycie

### 1. Uruchom signaling server (na serwerze nginx):

```bash
python3 signaling-server.py
```

Sprawdź czy działa:
```bash
curl http://localhost:8080/api/sessions
# Powinno zwrócić: []
```

### 2. Uruchom na Raspberry Pi:

```bash
cd ~/NetRC
source venv/bin/activate
export CF_REALTIME_APP_ID="your-cloudflare-app-id"
export CF_REALTIME_TOKEN="your-cloudflare-app-secret"
export SIGNALING_SERVER="http://79-76-127-159.nip.io:8080"
python3 car-client.py
```

Aplikacja wyświetli **Session ID** i zarejestruje się w signaling serverze.

### 3. Otwórz w przeglądarce:

Otwórz `index.html` w przeglądarce i:
1. Wpisz **App ID**
2. Wpisz **App Secret**
3. Zostaw **Signaling Server**: `http://79-76-127-159.nip.io:8080`
4. Kliknij **Refresh Sessions** - powinieneś zobaczyć sesję RPi
5. Wybierz sesję z listy
6. Kliknij **Connect**

## Architektura

