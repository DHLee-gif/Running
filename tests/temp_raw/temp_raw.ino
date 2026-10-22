#include <Wire.h>

#define TEMP_ADDR 0x48

void enablePullups() {   // MAX30102 모듈의 1.8V 풀업이 같은 선에 있으니 계속 필요
  NRF_P0->PIN_CNF[26] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);
  NRF_P0->PIN_CNF[27] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);
}

float readTemp() {
  Wire.beginTransmission(TEMP_ADDR);
  Wire.write(0x00);                          // 온도 레지스터
  if (Wire.endTransmission(false) != 0) return NAN;
  Wire.requestFrom((uint8_t)TEMP_ADDR, (uint8_t)2);
  if (Wire.available() < 2) return NAN;
  int16_t raw = (Wire.read() << 8) | Wire.read();
  return raw / 256.0;                        // 1칸 = 0.00390625°C
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  Wire.begin();
  Wire.setClock(100000);
  enablePullups();
  Serial.println("t_ms,temp");
}

void loop() {
  Serial.print(millis());
  Serial.print(",");
  Serial.println(readTemp(), 3);
  delay(500);
}