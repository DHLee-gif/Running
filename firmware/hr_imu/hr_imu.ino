#include <Wire.h>
#include "MAX30105.h"

#define IMU_ADDR 0x6A

MAX30105 ppg;
unsigned long lastData = 0;

// ===== nRF52840 내부 풀업 (MAX30102 모듈의 1.8V 풀업 보완) =====
void enablePullups() {
  NRF_P0->PIN_CNF[26] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);  // SDA
  NRF_P0->PIN_CNF[27] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);  // SCL
}

// ===== IMU (LSM6DS3TR-C) =====
void imuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(IMU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool imuInit() {
  Wire.beginTransmission(IMU_ADDR);
  Wire.write(0x0F);                                  // WHO_AM_I
  if (Wire.endTransmission(false) != 0) return false;
  Wire.requestFrom((uint8_t)IMU_ADDR, (uint8_t)1);
  if (!Wire.available() || Wire.read() != 0x6A) return false;

  imuWrite(0x12, 0x44);   // CTRL3_C: 읽는 도중 값이 안 바뀌게(BDU) + 주소 자동 증가
  imuWrite(0x10, 0x4C);   // CTRL1_XL: 가속도 104Hz, ±8g
  imuWrite(0x11, 0x44);   // CTRL2_G : 자이로 104Hz, ±500dps
  return true;
}

void imuRead(float a[3], float g[3]) {
  uint8_t b[12] = {0};
  Wire.beginTransmission(IMU_ADDR);
  Wire.write(0x22);                                  // 자이로 X부터 12바이트 (자이로 6 + 가속도 6)
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)IMU_ADDR, (uint8_t)12);
  for (int i = 0; i < 12 && Wire.available(); i++) b[i] = Wire.read();

  for (int i = 0; i < 3; i++) {
    int16_t rg = (int16_t)(b[2 * i]     | (b[2 * i + 1] << 8));
    int16_t ra = (int16_t)(b[6 + 2 * i] | (b[7 + 2 * i] << 8));
    g[i] = rg * 0.0175f;     // ±500dps → 17.5 mdps/LSB
    a[i] = ra * 0.000244f;   // ±8g    → 0.244 mg/LSB
  }
}

// ===== 전체 설정 =====
void setupAll() {
  Wire.begin();
  enablePullups();

  while (!ppg.begin(Wire, I2C_SPEED_STANDARD)) {     // 100kHz
    enablePullups();                                 // begin()이 꺼버린 풀업 다시 켜기
    Serial.println("# MAX30102를 찾을 수 없음");
    delay(1000);
  }
  enablePullups();
  ppg.setup(0x3F, 4, 2, 400, 411, 4096);             // ~100Hz, Red+IR

  while (!imuInit()) {
    Serial.println("# IMU(0x6A)를 찾을 수 없음");
    delay(1000);
  }
  Serial.println("# 준비 완료");
  lastData = millis();
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  setupAll();
  Serial.println("t_ms,red,ir,ax,ay,az,gx,gy,gz");
}

void loop() {
  ppg.check();
  while (ppg.available()) {
    float a[3], g[3];
    imuRead(a, g);

    Serial.print(millis());          Serial.print(",");
    Serial.print(ppg.getFIFORed());  Serial.print(",");
    Serial.print(ppg.getFIFOIR());
    for (int i = 0; i < 3; i++) { Serial.print(","); Serial.print(a[i], 3); }
    for (int i = 0; i < 3; i++) { Serial.print(","); Serial.print(g[i], 2); }
    Serial.println();

    ppg.nextSample();
    lastData = millis();
  }

  if (millis() - lastData > 1000) {
    Serial.println("# 센서 응답 없음. 다시 설정");
    setupAll();
  }
}