#include <Wire.h>

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
}

void loop() {
  Serial.print("SDA = ");
  Serial.print(g_ADigitalPinMap[PIN_WIRE_SDA]);
  Serial.print(",  SCL = ");
  Serial.println(g_ADigitalPinMap[PIN_WIRE_SCL]);
  delay(2000);
}