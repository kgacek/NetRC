#!/usr/bin/env python3
# filepath: /Users/user/code/NetRC/sbc/keyboard_control.py
import serial
import sys
import termios
import tty
import time

UART_DEV = "/dev/ttyS0"
UART_BAUD = 115200

# Wartości sterowania
THROTTLE_STEP = 100
STEER_STEP = 200
MAX_THROTTLE = 1000
MAX_STEER = 1000

# Stan
current_throttle = 0
current_steer = 0
seq = 0

ser = None

def init_uart():
    global ser
    try:
        ser = serial.Serial(UART_DEV, UART_BAUD, timeout=0.1)
        print(f"✓ UART opened: {UART_DEV} @ {UART_BAUD}")
        time.sleep(0.2)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        return True
    except Exception as e:
        print(f"✗ UART error: {e}")
        return False

def send_command(throttle, steer, flags=0):
    global seq
    seq = (seq + 1) & 0xFFFF
    cmd = f"T,{int(throttle)},{int(steer)},{int(flags)},{seq}\n"
    try:
        ser.write(cmd.encode('ascii'))
        ser.flush()
    except Exception as e:
        print(f"Send error: {e}")

def clamp(val, min_val, max_val):
    return max(min_val, min(max_val, val))

def print_status():
    # Clear line
    sys.stdout.write('\r')
    sys.stdout.write(' ' * 80)
    sys.stdout.write('\r')
    
    # Print status
    thr_bar = '█' * (abs(current_throttle) // 100)
    steer_bar = '█' * (abs(current_steer) // 100)
    
    thr_dir = "FWD" if current_throttle > 0 else "REV" if current_throttle < 0 else "---"
    steer_dir = "RIGHT" if current_steer > 0 else "LEFT " if current_steer < 0 else "-----"
    
    sys.stdout.write(f"Throttle: {thr_dir} {current_throttle:+5d} [{thr_bar:10s}] | Steer: {steer_dir} {current_steer:+5d} [{steer_bar:10s}]")
    sys.stdout.flush()

def main():
    global current_throttle, current_steer
    
    print("=== RC Car Keyboard Control ===")
    print("Controls:")
    print("  ↑ / ↓  - Forward / Reverse")
    print("  ← / →  - Left / Right")
    print("  SPACE  - Stop (neutral)")
    print("  q      - Quit")
    print("  a      - ARM ESC")
    print()
    
    if not init_uart():
        return
    
    # Wait for READY
    print("Waiting for ESP32 READY...")
    start = time.time()
    while time.time() - start < 3:
        if ser.in_waiting:
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if line:
                print(f"ESP32: {line}")
            if "READY" in line:
                break
    
    print("\n✓ Ready! Use arrow keys to control.\n")
    
    # Save terminal settings
    old_settings = termios.tcgetattr(sys.stdin)
    
    try:
        # Set terminal to raw mode
        tty.setraw(sys.stdin.fileno())
        
        print_status()
        
        while True:
            # Read key
            char = sys.stdin.read(1)
            
            # Check for escape sequences (arrow keys)
            if char == '\x1b':
                char += sys.stdin.read(2)
                
                if char == '\x1b[A':  # Up arrow
                    current_throttle = clamp(current_throttle + THROTTLE_STEP, -MAX_THROTTLE, MAX_THROTTLE)
                elif char == '\x1b[B':  # Down arrow
                    current_throttle = clamp(current_throttle - THROTTLE_STEP, -MAX_THROTTLE, MAX_THROTTLE)
                elif char == '\x1b[D':  # Left arrow
                    current_steer = clamp(current_steer - STEER_STEP, -MAX_STEER, MAX_STEER)
                elif char == '\x1b[C':  # Right arrow
                    current_steer = clamp(current_steer + STEER_STEP, -MAX_STEER, MAX_STEER)
            
            elif char == ' ':  # Space - stop
                current_throttle = 0
                current_steer = 0
            
            elif char == 'a':  # ARM
                print("\nSending ARM command...")
                ser.write(b"A,1\n")
                ser.flush()
                time.sleep(0.1)
                print_status()
            
            elif char == 'q':  # Quit
                print("\n\nStopping and quitting...")
                current_throttle = 0
                current_steer = 0
                send_command(0, 0, 1)
                break
            
            elif char == '\x03':  # Ctrl+C
                break
            
            # Send command
            send_command(current_throttle, current_steer)
            
            # Update display
            print_status()
            
            # Small delay
            time.sleep(0.05)
    
    finally:
        # Restore terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        
        # Stop car
        send_command(0, 0, 1)
        
        # Close serial
        if ser:
            ser.close()
        
        print("\n\n✓ Stopped")

if __name__ == '__main__':
    main()