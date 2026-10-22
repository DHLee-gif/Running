#include <Wire.h>
#include "MAX30105.h"

MAX30105 sensor;
unsigned long lastData = 0;

// nRF52840 내부 풀업 켜기 (MAX30102 모듈의 1.8V 풀업 보완)
// Wire.begin()이 핀 설정을 덮어쓰므로, 호출될 때마다 다시 켜야 함
void enablePullups() {
  NRF_P0->PIN_CNF[26] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);  // SDA (P0.26)
  NRF_P0->PIN_CNF[27] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);  // SCL (P0.27)
}

void setupSensor() {
  Wire.begin();
  enablePullups();                                    // 첫 통신 전에 풀업 켜기

  while (!sensor.begin(Wire, I2C_SPEED_STANDARD)) {   // 400kHz → 100kHz
    enablePullups();                                  // begin()이 꺼버린 풀업 다시 켜기
    Serial.println("MAX30102를 찾을 수 없음. 배선 확인");
    delay(1000);
  }
  enablePullups();                                    // begin() 성공 후에도 다시 켜기

  sensor.setup(0x1F, 4, 2, 400, 411, 16384);
//              ↑ LED 밝기 낮춤          ↑ 측정 범위 4배로 넓힘
  Serial.println("MAX30102 설정 완료");
  lastData = millis();
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  setupSensor();
  Serial.println("t_ms,red,ir");
}

void loop() {
  sensor.check();
  while (sensor.available()) {
    Serial.print(millis()); Serial.print(",");
    Serial.print(sensor.getFIFORed()); Serial.print(",");
    Serial.println(sensor.getFIFOIR());
    sensor.nextSample();
    lastData = millis();
  }
  if (millis() - lastData > 1000) {
    Serial.println("센서 응답 없음. 다시 설정");
    setupSensor();
  }
}