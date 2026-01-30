#include <Arduino.h>

HardwareSerial &U = Serial1;

// PINY
const int PIN_THROTTLE_PWM = 7;
const int PIN_SERVO        = 6;

const int UART_RX = 20;
const int UART_TX = 21;

// PWM
const int PWM_FREQ = 50;
const int PWM_RES_BITS = 12;

const uint32_t FAILSAFE_MS = 350;

int chThr = -1;
int chSrv = -1;

uint32_t lastPktMs = 0;

int clampi(int v, int lo, int hi){ return v<lo?lo:(v>hi?hi:v); }

void setThrottle(int thr){
  // WLtoys ESC używa odwróconej logiki:
  // 0    -> 1500us (neutral/stop)
  // 1000 -> 1000us (full forward)
  // -1000-> 2000us (full reverse)
  
  thr = clampi(thr, -1000, 1000);
  
  // Mapuj: -1000..0..1000 -> 2000us..1500us..1000us
  int us;
  if(thr == 0) {
    us = 1500;  // Neutral
  } else if(thr > 0) {
    // Forward: 1..1000 -> 1499..1000us
    us = 1500 - (thr * 500) / 1000;
  } else {
    // Reverse: -1..-1000 -> 1501..2000us
    us = 1500 + (-thr * 500) / 1000;
  }
  
  us = clampi(us, 1000, 2000);
  
  uint32_t top = (1UL << PWM_RES_BITS) - 1;
  uint32_t duty = (uint32_t)((us / 20000.0f) * top);
  
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

// WLtoys ESC nie wymaga armingu - wystarczy neutral
void armESC(){
  Serial.println("=== WLtoys ESC Init ===");
  
  // WLtoys ESC startuje na neutral (1500us)
  Serial.println("Setting neutral (1500us) - 2s");
  setThrottle(0);
  delay(2000);
  
  Serial.println("ESC ready!");
}

// T,<thr>,<steer>,<flags>,<seq>
// UWAGA: thr teraz może być ujemne dla reverse!
bool parseLine(const String &l, int &thr, int &steer, int &flags){
  if (!l.startsWith("T,")) return false;
  int p1=l.indexOf(',',2), p2=l.indexOf(',',p1+1), p3=l.indexOf(',',p2+1);
  if(p1<0||p2<0||p3<0) return false;
  thr=l.substring(2,p1).toInt();
  steer=l.substring(p1+1,p2).toInt();
  flags=l.substring(p2+1,p3).toInt();
  return true;
}

bool parseArmCommand(const String &l){
  return l.startsWith("A,");
}

void setup(){
  Serial.begin(115200);
  U.begin(115200, SERIAL_8N1, UART_RX, UART_TX);

  chThr = ledcAttach(PIN_THROTTLE_PWM, PWM_FREQ, PWM_RES_BITS);
  chSrv = ledcAttach(PIN_SERVO, PWM_FREQ, PWM_RES_BITS);

  // Start z neutral (1500us) - WAŻNE dla WLtoys!
  setThrottle(0);
  setSteer(0);
  lastPktMs = millis();

  Serial.println("\n=== ESP32 UART Control - WLtoys ===");
  Serial.printf("LEDC: throttle=%d servo=%d @ %dHz\n", chThr, chSrv, PWM_FREQ);
  Serial.println("Throttle logic: 0=neutral(1500us), +1000=forward(1000us), -1000=reverse(2000us)");
  
  delay(200);
  while(U.available()) U.read();
  
  U.println("READY");
  Serial.println("Sent READY to RPi\n");
}

void loop(){
  static String buf;
  static uint32_t rxCount = 0;

  while(U.available()){
    char c=(char)U.read();
    
    if(c=='\n'){
      rxCount++;
      
      Serial.printf("[RX #%lu] '%s'\n", rxCount, buf.c_str());
      
      // ARM (opcjonalne dla WLtoys)
      if(parseArmCommand(buf)){
        Serial.println("  -> ARM command");
        armESC();
        U.println("ACK,ARMED");
        buf="";
        continue;
      }
      
      // Control
      int thr=0, steer=0, flags=0;
      if(parseLine(buf, thr, steer, flags)){
        lastPktMs = millis();
        
        Serial.printf("  -> OK: thr=%d steer=%d flags=%d\n", thr, steer, flags);
        
        if(flags & 0x01) {
          setThrottle(0);  // Neutral
        } else {
          setThrottle(thr);
        }
        setSteer(steer);
        
        U.printf("ACK,%lu,%d,%d\n", rxCount, thr, steer);
      } else {
        Serial.println("  -> PARSE ERROR");
      }
      
      buf="";
    } else if(c!='\r'){
      if(buf.length()<120) buf += c;
    }
  }

  // Failsafe - neutral
  if(millis() - lastPktMs > FAILSAFE_MS){
    setThrottle(0);
    setSteer(0);
  }
}
