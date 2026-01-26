# Przewodnik debugowania "Backend error"

## Krok 1: Włącz DEBUG logging na RPi

```bash
# W car-client.py zmień poziom logowania
logging.basicConfig(level=logging.DEBUG)
```

## Krok 2: Sprawdź logi RPi

Uruchom car-client.py i zapisz pełne logi:
```bash
python car-client.py 2>&1 | tee rpi-debug.log
```

Szukaj w logach:
- Czy `sessionId` zostało utworzone?
- Jaki `mid` został wyodrębniony?
- Jaka jest pełna odpowiedź od Cloudflare?

## Krok 3: Sprawdź logi w przeglądarce

Otwórz DevTools (F12) -> Console i szukaj:
- Pełnego payload wysyłanego do Cloudflare
- Pełnej odpowiedzi od Cloudflare
- Błędów track-owych

## Krok 4: Sprawdź czy RPi faktycznie publikuje track

Po uruchomieniu car-client.py, sprawdź w konsoli czy widzisz:
