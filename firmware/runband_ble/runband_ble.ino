// RunBand 2단계: BLE 명령 받기
// 명령(START / STOP / STATUS)을 BLE(NUS) 또는 USB 시리얼로 받음
// 응답은 한 줄 텍스트: "OK ...", "ERR ...", "STATUS ...", 측정 중에는 "DATA ..."
#include <bluefruit.h>

BLEUart bleuart;   // Nordic UART Service (NUS)

// ===== 측정 상태 =====
bool running = false;
unsigned long runStart = 0;    // 측정 시작 시각 (millis)
uint32_t counter = 0;          // 3단계 전까지 가짜 데이터
unsigned long lastSend = 0;

// ===== 명령 입력 버퍼 =====
char bleBuf[32];  uint8_t bleLen = 0;  unsigned long bleLast = 0;
char serBuf[32];  uint8_t serLen = 0;  unsigned long serLast = 0;
const unsigned long CMD_TIMEOUT = 50;  // 줄바꿈 없이 와도 50ms 조용하면 명령으로 처리

// ===== 출력: BLE(연결 시) + 시리얼 =====
void sendLine(const char* s) {
  if (Bluefruit.connected() && bleuart.notifyEnabled()) {
    bleuart.write((const uint8_t*)s, strlen(s));
    bleuart.write((const uint8_t*)"\n", 1);
  }
  Serial.println(s);
}

void sendStatus() {
  char msg[80];
  unsigned long t = running ? millis() - runStart : 0;
  snprintf(msg, sizeof(msg), "STATUS state=%s t_ms=%lu count=%lu",
           running ? "RUN" : "IDLE", t, (unsigned long)counter);
  sendLine(msg);
}

// ===== 명령 처리 =====
void handleCommand(char* cmd) {
  // 앞뒤 공백 제거 + 대문자로
  while (*cmd == ' ') cmd++;
  int n = strlen(cmd);
  while (n > 0 && cmd[n - 1] == ' ') cmd[--n] = 0;
  if (n == 0) return;
  for (int i = 0; i < n; i++) cmd[i] = toupper(cmd[i]);

  if (strcmp(cmd, "START") == 0) {
    if (running) { sendLine("ERR already running"); return; }
    running = true;
    runStart = millis();
    counter = 0;
    lastSend = runStart;
    sendLine("OK START");
  } else if (strcmp(cmd, "STOP") == 0) {
    if (!running) { sendLine("ERR not running"); return; }
    running = false;
    char msg[48];
    snprintf(msg, sizeof(msg), "OK STOP t_ms=%lu", millis() - runStart);
    sendLine(msg);
  } else if (strcmp(cmd, "STATUS") == 0) {
    sendStatus();
  } else {
    char msg[48];
    snprintf(msg, sizeof(msg), "ERR unknown %s", cmd);
    sendLine(msg);
  }
}

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

// ===== 연결 / 끊김 콜백 =====
void onConnect(uint16_t conn) {
  BLEConnection* c = Bluefruit.Connection(conn);
  char peer[32] = {0};
  c->getPeerName(peer, sizeof(peer));
  Serial.print("# 연결됨: ");
  Serial.println(peer);
}

void onDisconnect(uint16_t conn, uint8_t reason) {
  // 측정은 계속 (다시 연결되면 STATUS로 확인)
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

  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);  // 큰 MTU/버퍼 허용 (3단계 대비)
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.setName("RunBand");
  Bluefruit.Periph.setConnectCallback(onConnect);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);

  bleuart.begin();
  startAdv();
  Serial.println("# RunBand 광고 시작 (명령: START / STOP / STATUS)");
}

void loop() {
  // 명령 받기 (BLE + USB 시리얼)
  while (bleuart.available()) feed((char)bleuart.read(), bleBuf, bleLen, bleLast);
  while (Serial.available())  feed((char)Serial.read(),  serBuf, serLen, serLast);
  flushIfIdle(bleBuf, bleLen, bleLast);
  flushIfIdle(serBuf, serLen, serLast);

  // 측정 중이면 1초마다 데이터 (3단계에서 센서 값으로 교체)
  if (running && millis() - lastSend >= 1000) {
    lastSend += 1000;
    counter++;
    char msg[48];
    snprintf(msg, sizeof(msg), "DATA t_ms=%lu count=%lu",
             millis() - runStart, (unsigned long)counter);
    sendLine(msg);
  }
}
