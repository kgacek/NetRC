#include <Arduino.h>

HardwareSerial &U = Serial1;

// PINY
const int PIN_THROTTLE_PWM = 3;
const int PIN_SERVO        = 4;

const int UART_RX = 20;
const int UART_TX = 21;

// PWM
const int PWM_FREQ     = 20000; // throttle
const int PWM_RES_BITS = 12;

const uint32_t FAILSAFE_MS = 350;

// ~1.0V przy 3.3V i 12 bit
const int DUTY_MIN = 1240;
const int DUTY_MAX = 4095;

int chThr = -1;
int chSrv = -1;

uint32_t lastPktMs = 0;

int clampi(int v, int lo, int hi){ return v<lo?lo:(v>hi?hi:v); }

void setThrottle(int thr){
  thr = clampi(thr, 0, 1000);
  int duty = map(thr, 0, 1000, DUTY_MIN, DUTY_MAX);
  ledcWrite(chThr, duty);
}

void setSteer(int steer){
  steer = clampi(steer, -1000, 1000);
  int us = 1500 + (steer * 500) / 1000;
  us = clampi(us, 1000, 2000);

  uint32_t top = (1UL << PWM_RES_BITS) - 1;
  uint32_t duty = (uint32_t)((us / 20000.0f) * top);
  ledcWrite(chSrv, duty);
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

void setup(){
  Serial.begin(115200);
  U.begin(115200, SERIAL_8N1, UART_RX, UART_TX);

  chThr = ledcAttach(PIN_THROTTLE_PWM, PWM_FREQ, PWM_RES_BITS);
  chSrv = ledcAttach(PIN_SERVO, 50, PWM_RES_BITS);

  setThrottle(0);
  setSteer(0);
  lastPktMs = millis();

  Serial.printf("LEDC channels: throttle=%d servo=%d\n", chThr, chSrv);
}

void loop(){
  static String buf;

  while(U.available()){
    char c=(char)U.read();
    if(c=='\n'){
      int thr=0, steer=0, flags=0;
      if(parseLine(buf, thr, steer, flags)){
        lastPktMs = millis();
        if(flags & 0x01) setThrottle(0);
        else setThrottle(thr);
        setSteer(steer);
      }
      buf="";
    } else if(c!='\r'){
      if(buf.length()<120) buf += c;
    }
  }

  if(millis() - lastPktMs > FAILSAFE_MS){
    setThrottle(0);
    setSteer(0);
  }
}
