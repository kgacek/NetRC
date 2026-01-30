#include <Arduino.h>

HardwareSerial &U = Serial1;

// PINY
const int PIN_THROTTLE_PWM = 7;
const int PIN_SERVO        = 6;

const int UART_RX = 20;
const int UART_TX = 21;

// PWM - OBA muszą być 50 Hz dla servo/ESC!
const int PWM_FREQ = 50;  // ZMIENIONE z 20000 na 50 Hz
const int PWM_RES_BITS = 12;

const uint32_t FAILSAFE_MS = 350;

int chThr = -1;
int chSrv = -1;

uint32_t lastPktMs = 0;

int clampi(int v, int lo, int hi){ return v<lo?lo:(v>hi?hi:v); }

void setThrottle(int thr){
  thr = clampi(thr, 0, 1000);
  // Mapuj 0-1000 na 1000-2000us pulse width
  int us = 1000 + (thr * 1000) / 1000;  // 0->1000us, 1000->2000us
  us = clampi(us, 1000, 2000);
  
  // Przelicz us na duty cycle dla 50Hz PWM
  uint32_t top = (1UL << PWM_RES_BITS) - 1;  // 4095 dla 12-bit
  uint32_t duty = (uint32_t)((us / 20000.0f) * top);  // 20ms period = 20000us
  
  ledcWrite(PIN_THROTTLE_PWM, duty);
  
}

void setSteer(int steer){
  steer = clampi(steer, -1000, 1000);
  int us = 1500 + (steer * 500) / 1000;
  us = clampi(us, 1000, 2000);

  uint32_t top = (1UL << PWM_RES_BITS) - 1;
  uint32_t duty = (uint32_t)((us / 20000.0f) * top);
  ledcWrite(PIN_SERVO, duty);
}

// Arming sequence dla ESC
void armESC(){
  Serial.println("Arming ESC...");
  
  // Krok 1: Maksymalny throttle (2000us pulse)
  Serial.println("  Step 1: Full throttle (2000us) - 2s");
  setThrottle(1000);  // Użyj setThrottle zamiast bezpośrednio ledcWrite
  delay(2000);
  
  // Krok 2: Minimalny throttle (1000us pulse)
  Serial.println("  Step 2: Zero throttle (1000us) - 3s");
  setThrottle(0);
  delay(3000);
  
  // Krok 3: Gotowe
  Serial.println("  Step 3: ESC armed! Should hear confirmation beeps.");
  delay(1000);
  
  Serial.println("ESC arming complete!");
}

// T,<thr>,<steer>,<flags>,<seq>
bool parseLine(const String &l, int &thr, int &steer, int &flags){
  if (!l.startsWith("T,")) return false;
  int p1=l.indexOf(',',2), p2=l.indexOf(',',p1+1), p3=l.indexOf(',',p2+1);
  if(p1<0||p2<0||p3<0) return false;
  thr=l.substring(2,p1).toInt();
  steer=l.substring(p1+1,p2).toInt();
  flags=l.substring(p2+1,p3).toInt();
  return true;
}

// Dodaj nowy typ komendy: A,<seq> - ARM ESC
bool parseArmCommand(const String &l){
  return l.startsWith("A,");
}

void setup(){
  Serial.begin(115200);
  U.begin(115200, SERIAL_8N1, UART_RX, UART_TX);

  // OBA kanały z 50 Hz
  chThr = ledcAttach(PIN_THROTTLE_PWM, PWM_FREQ, PWM_RES_BITS);
  chSrv = ledcAttach(PIN_SERVO, PWM_FREQ, PWM_RES_BITS);

  setThrottle(0);
  setSteer(0);
  lastPktMs = millis();

  Serial.println("ESP32 UART Control Ready");
  Serial.printf("LEDC channels: throttle=%d servo=%d @ %dHz\n", chThr, chSrv, PWM_FREQ);
  
  // Wyczyść bufor UART
  delay(200);
  while(U.available()) U.read();
  
  U.println("READY");
  Serial.println("Sent READY to RPi");
}

void loop(){
  static String buf;
  static uint32_t rxCount = 0;

  while(U.available()){
    char c=(char)U.read();
    
    if(c=='\n'){
      rxCount++;
      
      // Debug - pokaż każdą otrzymaną linię
      Serial.printf("[RX #%lu] '%s'\n", rxCount, buf.c_str());
      
      // Komenda ARM
      if(parseArmCommand(buf)){
        Serial.println("  -> ARM command");
        armESC();
        U.println("ACK,ARMED");
        buf="";
        continue;
      }
      
      // Normalna komenda sterowania
      int thr=0, steer=0, flags=0;
      if(parseLine(buf, thr, steer, flags)){
        lastPktMs = millis();
        
        Serial.printf("  -> OK: thr=%d steer=%d flags=%d\n", thr, steer, flags);
        
        if(flags & 0x01) {
          setThrottle(0);
        } else {
          setThrottle(thr);
        }
        setSteer(steer);
        
        // Wyślij ACK
        U.printf("ACK,%lu,%d,%d\n", rxCount, thr, steer);
      } else {
        Serial.println("  -> PARSE ERROR");
      }
      
      buf="";
    } else if(c!='\r'){
      if(buf.length()<120) buf += c;
    }
  }

  // Failsafe
  if(millis() - lastPktMs > FAILSAFE_MS){
    setThrottle(0);
    setSteer(0);
  }
}
