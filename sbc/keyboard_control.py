#!/usr/bin/env python3
# filepath: /Users/user/code/NetRC/sbc/keyboard_control.py
import serial
import sys
import termios
import tty
import time
import select

UART_DEV = "/dev/ttyS0"
UART_BAUD = 115200

# Wartości sterowania
THROTTLE_ACCEL = 10      # Jak szybko przyspiesza
THROTTLE_DECEL = 20      # Jak szybko hamuje
STEER_SPEED = 70         # Prędkość skrętu
STEER_RETURN_SPEED = 80  # Jak szybko wraca do środka
MAX_THROTTLE = 300
MAX_STEER = 1000

# Stan pojazdu
throttle = 0
steer = 0
seq = 0

# Aktualnie wciśnięte klawisze (ciągłe wykrywanie)
keys = {
    'w': False,  # Forward
    's': False,  # Reverse
    'a': False,  # Left
    'd': False   # Right
}

ser = None

def init_uart():
    global ser
    try:
        ser = serial.Serial(UART_DEV, UART_BAUD, timeout=0.1)
        print(f"✓ UART: {UART_DEV} @ {UART_BAUD}")
        time.sleep(0.2)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        return True
    except Exception as e:
        print(f"✗ UART error: {e}")
        return False

def send_command(thr, st):
    global seq
    seq = (seq + 1) & 0xFFFF
    cmd = f"T,{int(thr)},{int(st)},0,{seq}\n"
    try:
        ser.write(cmd.encode('ascii'))
        ser.flush()
    except:
        pass

def clamp(val, min_val, max_val):
    return max(min_val, min(max_val, val))

def draw_bar(value, max_val, width=10):
    filled = int((abs(value) / max_val) * width)
    return '█' * filled + '░' * (width - filled)

def print_hud():
    sys.stdout.write('\r' + ' ' * 120 + '\r')
    
    # Throttle bar
    thr_bar = draw_bar(throttle, MAX_THROTTLE, 20)
    thr_label = "FWD" if throttle > 0 else "REV" if throttle < 0 else "---"
    
    # Steer bar with center indicator
    steer_pct = steer / MAX_STEER
    steer_pos = int((steer_pct + 1) * 10)  # 0-20 pozycja
    steer_bar = '░' * 10 + '|' + '░' * 10
    steer_bar = steer_bar[:steer_pos] + '█' + steer_bar[steer_pos+1:]
    
    # Keys indicator
    key_w = '▲' if keys['w'] else '△'
    key_s = '▼' if keys['s'] else '▽'
    key_a = '◄' if keys['a'] else '◁'
    key_d = '►' if keys['d'] else '▷'
    
    sys.stdout.write(
        f"[{thr_label}] {thr_bar} {throttle:+5d}  |  "
        f"[STEER] {steer_bar} {steer:+5d}  |  "
        f"[{key_w}{key_s}{key_a}{key_d}]"
    )
    sys.stdout.flush()

def update_vehicle():
    global throttle, steer
    
    # === THROTTLE (jak w grze - W/S) ===
    if keys['w'] and not keys['s']:
        # W wciśnięty - przyśpieszaj do przodu
        throttle = min(50+throttle + THROTTLE_ACCEL, MAX_THROTTLE)
    elif keys['s'] and not keys['w']:
        # S wciśnięty - przyśpieszaj do tyłu
        throttle = max(throttle - THROTTLE_ACCEL-50, -MAX_THROTTLE)
    else:
        # Brak W/S - hamuj do zera
        if throttle > 0:
            throttle = max(0, throttle - THROTTLE_DECEL)
        elif throttle < 0:
            throttle = min(0, throttle + THROTTLE_DECEL)
    
    # === STEERING (jak w grze - A/D) ===
    if keys['a'] and not keys['d']:
        # A wciśnięty - skręcaj w lewo
        steer = min(steer + STEER_SPEED, MAX_STEER)
    elif keys['d'] and not keys['a']:
        # D wciśnięty - skręcaj w prawo
        steer = max(steer - STEER_SPEED, -MAX_STEER)
    else:
        # Brak A/D - wracaj do środka
        if steer > 0:
            steer = max(0, steer - STEER_RETURN_SPEED)
        elif steer < 0:
            steer = min(0, steer + STEER_RETURN_SPEED)

def get_char_nonblocking():
    """Odczytaj znak bez blokowania"""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None

def main():
    global throttle, steer
    
    print("╔════════════════════════════════════════╗")
    print("║    RC Car - Game-Style Control        ║")
    print("╚════════════════════════════════════════╝")
    print()
    print("  W / S  - Forward / Reverse (progressive)")
    print("  A / D  - Left / Right (auto-center)")
    print("  SPACE  - Emergency brake")
    print("  R      - Reset (center + stop)")
    print("  Q      - Quit")
    print()
    
    if not init_uart():
        return
    
    # Czekaj na READY
    print("Waiting for ESP32...")
    start = time.time()
    while time.time() - start < 3:
        if ser.in_waiting:
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if "READY" in line:
                print(f"✓ {line}\n")
                break
    
    # Terminal raw mode
    old_settings = termios.tcgetattr(sys.stdin)
    
    try:
        tty.setraw(sys.stdin.fileno())
        print_hud()
        
        last_update = time.time()
        last_key_time = {}
        KEY_REPEAT_TIMEOUT = 0.05  # 50ms bez klawisza = zwolniony
        
        while True:
            now = time.time()
            
            # Odczytaj klawisz
            char = get_char_nonblocking()
            
            if char:
                if char == 'w':
                    keys['w'] = True
                    last_key_time['w'] = now
                elif char == 's':
                    keys['s'] = True
                    last_key_time['s'] = now
                elif char == 'a':
                    keys['a'] = True
                    last_key_time['a'] = now
                elif char == 'd':
                    keys['d'] = True
                    last_key_time['d'] = now
                elif char == ' ':  # Emergency brake
                    throttle = 0
                    steer = 0
                    keys = {'w': False, 's': False, 'a': False, 'd': False}
                elif char == 'r':  # Reset
                    throttle = 0
                    steer = 0
                    keys = {'w': False, 's': False, 'a': False, 'd': False}
                elif char == 'q':  # Quit
                    break
                elif char == '\x03':  # Ctrl+C
                    break
            
            # Sprawdź timeout klawiszy (wykryj zwolnienie)
            for key in ['w', 's', 'a', 'd']:
                if keys[key] and (now - last_key_time.get(key, 0)) > KEY_REPEAT_TIMEOUT:
                    keys[key] = False
            
            # Update pojazdu (50Hz)
            if now - last_update >= 0.02:
                update_vehicle()
                send_command(throttle, steer)
                print_hud()
                last_update = now
            
            time.sleep(0.005)
    
    except KeyboardInterrupt:
        pass
    
    finally:
        # Restore terminal
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        
        # Stop
        throttle = 0
        steer = 0
        send_command(0, 0)
        time.sleep(0.1)
        
        if ser:
            ser.close()
        
        print("\n\n✓ Stopped")

if __name__ == '__main__':
    main()