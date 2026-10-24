// RunBand 3단계: 센서 데이터 BLE 전송
// - 명령/상태/온도/이벤트: NUS (텍스트 한 줄)
//     받는 명령: START / STOP / STATUS
//     보내는 줄: OK ..., ERR ..., STATUS ..., TEMP ..., EVT ...
// - PPG+IMU 원본(약 100Hz): RunBand Data 서비스 (바이너리 묶음)
//     패킷 = [0x01][샘플 수 n][seq 2B] + n × 22B
//     샘플 = t_ms 4B, red 3B, ir 3B, ax ay az gx gy gz 각 2B (원본 정수, 리틀엔디언)
#include <bluefruit.h>
#include <Wire.h>
#include "MAX30105.h"

#define IMU_ADDR  0x6A
#define TEMP_ADDR 0x48

// ===== BLE =====
BLEUart bleuart;   // Nordic UART Service (NUS)
// 데이터 서비스 7a1e0001-5c3b-4f0e-9d2a-6b8f1c2e3d40 / 특성 7a1e0002-... (바이트는 거꾸로 적음)
const uint8_t DATA_SVC_UUID[16] = {0x40, 0x3d, 0x2e, 0x1c, 0x8f, 0x6b, 0x2a, 0x9d,
                                   0x0e, 0x4f, 0x3b, 0x5c, 0x01, 0x00, 0x1e, 0x7a};
const uint8_t DATA_CHR_UUID[16] = {0x40, 0x3d, 0x2e, 0x1c, 0x8f, 0x6b, 0x2a, 0x9d,
                                   0x0e, 0x4f, 0x3b, 0x5c, 0x02, 0x00, 0x1e, 0x7a};
BLEService        dataSvc(DATA_SVC_UUID);
BLECharacteristic dataChr(DATA_CHR_UUID);

// ===== 샘플 / 큐 (센서 작업 → 메인 루프) =====
struct Sample {
  uint32_t t;        // START 후 경과 ms
  uint32_t red, ir;
  int16_t  imu[6];   // ax ay az gx gy gz (원본 정수)
};
QueueHandle_t q;
const int QUEUE_LEN = 300;   // 약 3초분 (전송이 잠깐 막혀도 버팀)

// ===== 공유 상태 (두 작업이 같이 씀) =====
volatile bool running = false;
volatile unsigned long runStart = 0;
volatile bool sensorsReady = false;
volatile bool ppgOk = false, imuOk = false, tempOk = false;
volatile bool tempNow = false;            // 온도 바로 읽기 요청
volatile int16_t  tempRaw = 0;
volatile bool     tempValid = false;
volatile uint32_t tempT = 0, tempSeq = 0;
volatile uint16_t ppgHz = 0;
volatile uint32_t produced = 0, qDrop = 0;  // 만든 샘플 수, 큐가 꽉 차서 버린 수

// =====================================================================
// 센서 (센서 작업에서만 I2C 사용)
// =====================================================================
MAX30105 ppg;
unsigned long lastPpg = 0;

// nRF52840 내부 풀업 (MAX30102 모듈의 1.8V 풀업 보완)
void enablePullups() {
  NRF_P0->PIN_CNF[26] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);  // SDA
  NRF_P0->PIN_CNF[27] |= (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);  // SCL
}

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
  if (Wire.requestFrom((uint8_t)IMU_ADDR, (uint8_t)1) != 1) return false;
  if (Wire.read() != 0x6A) return false;
  imuWrite(0x12, 0x44);   // CTRL3_C: BDU + 주소 자동 증가
  imuWrite(0x10, 0x4C);   // CTRL1_XL: 104Hz, ±8g
  imuWrite(0x11, 0x44);   // CTRL2_G : 104Hz, ±500dps
  return true;
}

// 0x22부터 12바이트 (자이로 6 + 가속도 6) → ax ay az gx gy gz 순서로
bool imuReadRaw(int16_t out[6]) {
  Wire.beginTransmission(IMU_ADDR);
  Wire.write(0x22);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)IMU_ADDR, (uint8_t)12) != 12) return false;
  uint8_t b[12];
  for (int i = 0; i < 12; i++) b[i] = Wire.read();
  for (int i = 0; i < 3; i++) {
    out[3 + i] = (int16_t)(b[2 * i]     | (b[2 * i + 1] << 8));   // 자이로
    out[i]     = (int16_t)(b[6 + 2 * i] | (b[7 + 2 * i] << 8));   // 가속도
  }
  return true;
}

// MAX30205: 레지스터 0x00 2바이트, raw/256 = °C
bool readTempRaw(int16_t& raw) {
  Wire.beginTransmission(TEMP_ADDR);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)TEMP_ADDR, (uint8_t)2) != 2) return false;
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  raw = (int16_t)((hi << 8) | lo);
  return true;
}

// 버스 전체 다시 설정 (begin()이 풀업을 끄므로 매번 다시 켬)
void sensorInit() {
  Wire.begin();
  enablePullups();
  ppgOk = ppg.begin(Wire, I2C_SPEED_STANDARD);       // 100kHz
  enablePullups();
  if (ppgOk) ppg.setup(0x3F, 4, 2, 400, 411, 4096);  // ~100Hz, Red+IR
  imuOk = imuInit();
  int16_t r;
  tempOk = readTempRaw(r);
  lastPpg = millis();
}

// 센서 작업: 5ms마다 PPG FIFO 확인 (라이브러리 버퍼가 4개뿐이라 자주 비워야 함)
void sensorLoop() {
  static unsigned long lastFix = 0, lastTemp = 0, hzStart = 0;
  static uint16_t hzCount = 0;

  if (!sensorsReady) {
    sensorInit();
    sensorsReady = true;
    lastFix = hzStart = millis();
  }

  // PPG + IMU (PPG 샘플 하나마다 IMU 한 번)
  if (ppgOk) {
    ppg.check();
    while (ppg.available()) {
      Sample s;
      s.red = ppg.getFIFORed();
      s.ir  = ppg.getFIFOIR();
      ppg.nextSample();
      if (!imuOk || !imuReadRaw(s.imu)) {      // IMU 끊기면 0으로 채움
        imuOk = false;
        memset(s.imu, 0, sizeof(s.imu));
      }
      hzCount++;
      lastPpg = millis();
      if (running) {
        s.t = millis() - runStart;
        produced++;
        if (xQueueSend(q, &s, 0) != pdTRUE) qDrop++;
      }
    }
    if (millis() - lastPpg > 1000) ppgOk = false;   // 1초간 새 샘플 없음
  }

  unsigned long now = millis();
  if (now - hzStart >= 1000) {         // 초당 PPG 샘플 수
    ppgHz = hzCount;
    hzCount = 0;
    hzStart = now;
  }

  // 온도: 10초마다 (START 직후엔 바로)
  if (tempNow || now - lastTemp >= 10000) {
    tempNow = false;
    lastTemp = now;
    int16_t r;
    if (readTempRaw(r)) {
      tempRaw = r;
      tempT = running ? millis() - runStart : 0;
      tempValid = true;
      tempOk = true;
      tempSeq++;
    } else {
      tempOk = false;
    }
  }

  // 끊긴 센서는 1초마다 다시 설정
  if (now - lastFix >= 1000 && (!ppgOk || !imuOk || !tempOk)) {
    lastFix = now;
    if (!ppgOk) {
      sensorInit();                    // PPG가 끊기면 버스 전체 다시
    } else {
      if (!imuOk) imuOk = imuInit();
      if (!tempOk) { int16_t r; tempOk = readTempRaw(r); }
    }
  }

  delay(5);   // 작업 쉬기 (메인 루프/BLE에 양보)
}

// =====================================================================
// 배터리 (메인 루프에서 10초마다)
// =====================================================================
// 분배 저항 비율은 보드 문서로 확인 못 함 → Adafruit 보드처럼 1/2로 가정
// 멀티미터 값과 다르면 이 숫자만 고치면 됨 (배터리 전압 / 핀 전압)
const float VBAT_RATIO = 2.0f;
uint16_t batMv = 0, batRaw = 0;
uint8_t  batPct = 0;

// 리튬폴리머 전압 → 대략적인 잔량 (부하·충전 중엔 오차 큼)
uint8_t lipoPercent(uint16_t mv) {
  const uint16_t V[] = {3300, 3600, 3700, 3750, 3800, 3900, 4000, 4100, 4200};
  const uint8_t  P[] = {0,    4,    13,   25,   40,   63,   78,   90,   100};
  if (mv <= V[0]) return 0;
  for (int i = 1; i < 9; i++) {
    if (mv <= V[i]) return P[i - 1] + (uint32_t)(P[i] - P[i - 1]) * (mv - V[i - 1]) / (V[i] - V[i - 1]);
  }
  return 100;
}

void readBattery() {
  analogReference(AR_INTERNAL_3_0);   // 0~3.0V
  analogReadResolution(12);
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogRead(PIN_VBAT);
  batRaw = sum / 8;
  batMv = (uint16_t)(batRaw * 3000.0f / 4096.0f * VBAT_RATIO);
  batPct = lipoPercent(batMv);
}

// =====================================================================
// BLE 전송 (메인 루프에서만 사용)
// =====================================================================
uint8_t  pkt[4 + 10 * 22];
uint8_t  pktN = 0;
uint16_t seq = 0;
unsigned long pktFirst = 0;
uint32_t sentN = 0;      // BLE로 보낸 샘플 수

uint16_t currentMtu() {
  if (!Bluefruit.connected()) return 0;
  BLEConnection* c = Bluefruit.Connection(Bluefruit.connHandle());
  if (!c) return 0;
  // 라이브러리가 MTU 교환 후 폰 쪽 값(예: 517)을 그대로 저장함 → 보드 한계 247로 자름
  uint16_t m = c->getMtu();
  return m > 247 ? 247 : m;
}

// MTU에 맞춰 한 패킷에 넣을 샘플 수 (MTU 247 → 10개)
uint8_t perPacket() {
  int n = ((int)currentMtu() - 3 - 4) / 22;
  return n < 1 ? 1 : (n > 10 ? 10 : n);
}

void putSample(const Sample& s) {
  uint8_t* p = pkt + 4 + pktN * 22;
  memcpy(p, &s.t, 4);          // nRF52는 리틀엔디언이라 그대로 복사
  memcpy(p + 4, &s.red, 3);
  memcpy(p + 7, &s.ir, 3);
  memcpy(p + 10, s.imu, 12);
  pktN++;
}

// 모은 샘플 전송. false = 버퍼가 꽉 차서 못 보냄 (다음에 다시)
bool flushPacket() {
  if (pktN == 0) return true;
  pkt[0] = 0x01;
  pkt[1] = pktN;
  pkt[2] = seq & 0xFF;
  pkt[3] = seq >> 8;
  if (Bluefruit.connected() && dataChr.notifyEnabled()) {
    if (!dataChr.notify(pkt, 4 + pktN * 22)) return false;
    sentN += pktN;
  }
  // 미연결이면 버림 (seq는 올려서 받는 쪽이 빠진 걸 알 수 있게)
  pktN = 0;
  seq++;
  return true;
}

// 큐 → 패킷. 꽉 차면 보내고, 200ms 지나면 덜 차도 보냄
void pumpData() {
  Sample s;
  while (true) {
    if (pktN >= perPacket() && !flushPacket()) return;
    if (xQueueReceive(q, &s, 0) != pdTRUE) break;
    if (pktN == 0) pktFirst = millis();
    putSample(s);
  }
  if (pktN > 0 && millis() - pktFirst >= 200) flushPacket();
}

// ===== 텍스트 출력: BLE(연결 시) + 시리얼 =====
void sendLine(const char* s) {
  if (Bluefruit.connected() && bleuart.notifyEnabled()) {
    // 줄바꿈까지 한 번에 전송 (따로 보내면 앱에 "\n"만 마지막 값으로 보임)
    char line[256];
    int n = snprintf(line, sizeof(line), "%s\n", s);
    bleuart.write((const uint8_t*)line, n);
    Serial.println(s);
  } else {
    // BLE로 못 보낸 이유를 시리얼에 표시
    Serial.print(s);
    Serial.println(Bluefruit.connected() ? "   [BLE 안 보냄: TX notify 꺼짐]"
                                         : "   [BLE 안 보냄: 미연결]");
  }
}

// 온도 raw → "31.234" (printf 실수 없이)
void fmtTemp(char* out, size_t n, int16_t raw) {
  long m = ((long)raw * 1000 + (raw >= 0 ? 128 : -128)) / 256;   // 밀리°C, 반올림
  snprintf(out, n, "%s%ld.%03ld", m < 0 ? "-" : "", labs(m) / 1000, labs(m) % 1000);
}

const char* okStr(bool ok) { return ok ? "ok" : "lost"; }

void sendStatus() {
  char tc[12] = "-";
  if (tempValid) fmtTemp(tc, sizeof(tc), tempRaw);
  char msg[256];
  snprintf(msg, sizeof(msg),
           "STATUS state=%s t_ms=%lu mtu=%u ppg=%s imu=%s temp=%s ppg_hz=%u temp_c=%s n=%lu sent=%lu qdrop=%lu"
           " bat_mv=%u bat_pct=%u bat_raw=%u",
           running ? "RUN" : "IDLE", running ? millis() - runStart : 0UL, currentMtu(),
           okStr(ppgOk), okStr(imuOk), okStr(tempOk), ppgHz, tc,
           (unsigned long)produced, (unsigned long)sentN, (unsigned long)qDrop,
           batMv, batPct, batRaw);
  sendLine(msg);
}

// ===== 명령 처리 =====
void startRun() {
  produced = qDrop = sentN = 0;
  pktN = 0;
  seq = 0;
  xQueueReset(q);
  runStart = millis();
  running = true;
  tempNow = true;          // 시작하자마자 온도 한 번
  sendLine("OK START");
}

void stopRun() {
  running = false;
  delay(10);               // 센서 작업이 넣던 샘플 마무리
  // 남은 데이터 모두 전송 (최대 3초)
  unsigned long t0 = millis();
  while (millis() - t0 < 3000) {
    pumpData();
    if (uxQueueMessagesWaiting(q) == 0 && flushPacket()) break;
  }
  char msg[96];
  snprintf(msg, sizeof(msg), "OK STOP t_ms=%lu n=%lu sent=%lu qdrop=%lu",
           millis() - runStart, (unsigned long)produced, (unsigned long)sentN,
           (unsigned long)qDrop);
  sendLine(msg);
}

void handleCommand(char* cmd) {
  // 앞뒤 공백 제거 + 대문자로
  while (*cmd == ' ') cmd++;
  int n = strlen(cmd);
  while (n > 0 && cmd[n - 1] == ' ') cmd[--n] = 0;
  if (n == 0) return;
  for (int i = 0; i < n; i++) cmd[i] = toupper(cmd[i]);

  if (strcmp(cmd, "START") == 0) {
    if (running) sendLine("ERR already running");
    else startRun();
  } else if (strcmp(cmd, "STOP") == 0) {
    if (!running) sendLine("ERR not running");
    else stopRun();
  } else if (strcmp(cmd, "STATUS") == 0) {
    sendStatus();
  } else {
    char msg[48];
    snprintf(msg, sizeof(msg), "ERR unknown %s", cmd);
    sendLine(msg);
  }
}

// ===== 명령 입력 버퍼 =====
char bleBuf[32];  uint8_t bleLen = 0;  unsigned long bleLast = 0;
char serBuf[32];  uint8_t serLen = 0;  unsigned long serLast = 0;
const unsigned long CMD_TIMEOUT = 50;  // 줄바꿈 없이 와도 50ms 조용하면 명령으로 처리

// 글자 하나씩 모아서 줄바꿈(또는 시간 초과) 시 명령 실행
void feed(char c, char* buf, uint8_t& len, unsigned long& last) {
  last = millis();
  if (c == '\n' || c == '\r') {
    buf[len] = 0;
    handleCommand(buf);
    len = 0;
  } else if (len < 31) {
    buf[len++] = c;
  }
}

void flushIfIdle(char* buf, uint8_t& len, unsigned long last) {
  if (len > 0 && millis() - last > CMD_TIMEOUT) {
    buf[len] = 0;
    handleCommand(buf);
    len = 0;
  }
}

// ===== 센서 상태 변화 → EVT 줄 =====
void reportChange(const char* name, bool now, int8_t& prev) {
  if (prev != (int8_t)now) {
    prev = now;
    char msg[32];
    snprintf(msg, sizeof(msg), "EVT %s=%s", name, okStr(now));
    sendLine(msg);
  }
}

// ===== 연결 / 끊김 콜백 =====
void onConnect(uint16_t conn) {
  BLEConnection* c = Bluefruit.Connection(conn);
  char peer[32] = {0};
  c->getPeerName(peer, sizeof(peer));
  Serial.print("# 연결됨: ");
  Serial.println(peer);

  // 한 번에 보내는 크기 늘리기 (기본 20바이트 → 최대 244바이트)
  c->requestPHY();                 // 가능하면 2Mbps
  c->requestDataLengthUpdate();
  c->requestMtuExchange(247);
}

void onDisconnect(uint16_t conn, uint8_t reason) {
  // 측정은 계속 (다시 연결되면 STATUS로 확인, 끊긴 동안 데이터는 버려짐)
  Serial.print("# 연결 끊김, reason=0x");
  Serial.println(reason, HEX);
}

// ===== 광고 =====
void startAdv() {
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addService(bleuart);   // NUS UUID 포함 (웹에서 필터용)
  Bluefruit.ScanResponse.addName();            // 이름은 스캔 응답에
  Bluefruit.Advertising.restartOnDisconnect(true);  // 끊기면 자동 재광고
  Bluefruit.Advertising.setInterval(32, 244);  // 20ms → 30초 뒤 152.5ms
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);              // 0 = 계속 광고
}

void setup() {
  Serial.begin(115200);   // while(!Serial) 없음: USB 없어도 바로 동작
  readBattery();

  q = xQueueCreate(QUEUE_LEN, sizeof(Sample));

  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);  // MTU 247까지 허용
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.setName("RunBand");
  Bluefruit.Periph.setConnectCallback(onConnect);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);

  // 데이터 서비스 (notify 전용)
  dataSvc.begin();
  dataChr.setProperties(CHR_PROPS_NOTIFY);
  dataChr.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  dataChr.setMaxLen(sizeof(pkt));
  dataChr.begin();

  bleuart.begin();
  startAdv();

  // 센서는 별도 작업에서 (BLE 전송이 잠깐 막혀도 샘플을 놓치지 않게)
  Scheduler.startLoop(sensorLoop, 2048, TASK_PRIO_NORMAL, "sensor");
  Serial.println("# RunBand 광고 시작 (명령: START / STOP / STATUS)");
}

void loop() {
  // USB 모니터가 새로 열리면 안내 + 상태 출력 (부팅 메시지는 놓치므로)
  static bool usbWas = false;
  bool usbNow = Serial;
  if (usbNow && !usbWas) {
    Serial.println("# RunBand 준비됨 (명령: START / STOP / STATUS)");
    Serial.print("# BLE 연결: ");
    Serial.println(Bluefruit.connected() ? "예" : "아니오");
    sendStatus();
  }
  usbWas = usbNow;

  // 명령 받기 (BLE + USB 시리얼)
  while (bleuart.available()) feed((char)bleuart.read(), bleBuf, bleLen, bleLast);
  while (Serial.available())  feed((char)Serial.read(),  serBuf, serLen, serLast);
  flushIfIdle(bleBuf, bleLen, bleLast);
  flushIfIdle(serBuf, serLen, serLast);

  // 센서 상태 변화 알림
  static int8_t pPpg = -1, pImu = -1, pTemp = -1;
  if (sensorsReady) {
    reportChange("ppg",  ppgOk,  pPpg);
    reportChange("imu",  imuOk,  pImu);
    reportChange("temp", tempOk, pTemp);
  }

  // 온도 (측정 중일 때만 전송)
  static uint32_t lastTempSeq = 0;
  if (tempSeq != lastTempSeq) {
    lastTempSeq = tempSeq;
    if (running) {
      char tc[12], msg[48];
      fmtTemp(tc, sizeof(tc), tempRaw);
      snprintf(msg, sizeof(msg), "TEMP t_ms=%lu c=%s", (unsigned long)tempT, tc);
      sendLine(msg);
    }
  }

  // 배터리 10초마다
  static unsigned long lastBat = 0;
  if (millis() - lastBat >= 10000) {
    lastBat = millis();
    readBattery();
  }

  // PPG+IMU 원본 전송
  if (running) pumpData();

  delay(2);
}
