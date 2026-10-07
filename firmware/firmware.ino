#include <Wire.h>

uint8_t IMU_ADDR = 0;
float gyroBias[3] = {0, 0, 0};

// 레지스터 주소 (LSM6DS3TR-C 데이터시트 기준)
const uint8_t WHO_AM_I  = 0x0F;
const uint8_t CTRL1_XL  = 0x10;
const uint8_t CTRL2_G   = 0x11;
const uint8_t CTRL3_C   = 0x12;
const uint8_t STATUS    = 0x1E;
const uint8_t OUTX_L_G  = 0x22;  // 여기서부터 12바이트: 자이로 XYZ, 가속도 XYZ

// 감도: ±8g -> 0.244 mg/LSB, ±500dps -> 17.5 mdps/LSB
const float ACC_SENS  = 0.000244f;
const float GYRO_SENS = 0.0175f;
const int   CALIB_SAMPLES = 200;   // 104Hz 기준 약 2초

void writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(IMU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

uint8_t readReg(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  Wire.requestFrom(addr, (uint8_t)1);
  return Wire.available() ? Wire.read() : 0xFF;
}

bool dataReady() {
  return (readReg(IMU_ADDR, STATUS) & 0x03) == 0x03;
}

// 가속도(g), 자이로(dps)를 읽어서 a[3], g[3]에 저장 (자이로는 보정값 적용)
void readIMU(float a[3], float g[3]) {
  Wire.beginTransmission(IMU_ADDR);
  Wire.write(OUTX_L_G);
  Wire.endTransmission(false);
  Wire.requestFrom(IMU_ADDR, (uint8_t)12);

  int16_t raw[6];
  for (int i = 0; i < 6; i++) {
    uint8_t lo = Wire.read();
    uint8_t hi = Wire.read();
    raw[i] = (int16_t)(hi << 8 | lo);
  }
  for (int i = 0; i < 3; i++) {
    g[i] = raw[i] * GYRO_SENS - gyroBias[i];
    a[i] = raw[i + 3] * ACC_SENS;
  }
}

void calibrateGyro() {
  Serial.println("자이로 보정 중... 움직이지 마세요");
  float sum[3] = {0, 0, 0};
  float a[3], g[3];
  int count = 0;
  while (count < CALIB_SAMPLES) {
    if (!dataReady()) continue;
    readIMU(a, g);
    for (int i = 0; i < 3; i++) sum[i] += g[i];
    count++;
  }
  for (int i = 0; i < 3; i++) gyroBias[i] = sum[i] / CALIB_SAMPLES;
  Serial.print("gyro bias (dps): ");
  Serial.print(gyroBias[0], 2); Serial.print(", ");
  Serial.print(gyroBias[1], 2); Serial.print(", ");
  Serial.println(gyroBias[2], 2);
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);
  Wire.begin();

  // 1) 주소 찾기 + WHO_AM_I 확인
  uint8_t candidates[] = {0x6A, 0x6B};
  for (uint8_t a : candidates) {
    uint8_t id = readReg(a, WHO_AM_I);
    Serial.print("addr 0x"); Serial.print(a, HEX);
    Serial.print(" -> WHO_AM_I 0x"); Serial.println(id, HEX);
    if (id == 0x6A) IMU_ADDR = a;
  }
  if (IMU_ADDR == 0) {
    Serial.println("IMU not found. 배선 확인!");
    while (1) delay(1000);
  }

  // 2) 설정
  writeReg(CTRL3_C,  0x44);  // BDU=1(데이터 깨짐 방지), IF_INC=1(연속 읽기)
  writeReg(CTRL1_XL, 0x4C);  // 가속도: 104Hz, ±8g
  writeReg(CTRL2_G,  0x44);  // 자이로: 104Hz, ±500dps
  delay(200);                // 설정 직후 불안정한 값 버리기

  // 3) 자이로 보정
  calibrateGyro();

  Serial.println("t_ms,ax,ay,az,gx,gy,gz");
}

void loop() {
  if (!dataReady()) return;   // 새 데이터가 있을 때만

  float a[3], g[3];
  readIMU(a, g);

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint < 3000) return;
  lastPrint = millis();

  Serial.print(millis()); Serial.print(',');
  Serial.print(a[0], 3); Serial.print(',');
  Serial.print(a[1], 3); Serial.print(',');
  Serial.print(a[2], 3); Serial.print(',');
  Serial.print(g[0], 2); Serial.print(',');
  Serial.print(g[1], 2); Serial.print(',');
  Serial.println(g[2], 2);
}