// RunBand 웹: Web Bluetooth 연결, 시작/멈춤, 실시간 표시, CSV 저장
const { UUID, A_SCALE } = Protocol;
const $ = id => document.getElementById(id);

const HR_WIN = 10;        // 심박/케이던스 계산 구간 (초)
const GRAPH_SEC = 8;      // 그래프 시간 폭 (초)
const STATIC_MIN = 9;     // 온도 안정까지 걸리는 시간 (분)

// ===== 상태 =====
let device = null, rxChar = null;
let userClosed = false, reconnectTimer = null, pollTimer = null;
let recording = false, savedData = false;
let lastSeq = null, pkts = 0, gaps = 0, secCount = 0, rxHz = 0;
let lastT = 0;                         // 마지막 샘플 시각 (보드 ms)
let wakeLock = null;
const rec = new Protocol.Recorder();
const live = { t: [], ir: [], a: [] };  // 최근 몇 초 (계산·그래프용)

// ===== 기록창 =====
function log(msg) {
  const el = $('log');
  const now = new Date().toTimeString().slice(0, 8);
  const lines = (now + ' ' + msg + '\n' + el.textContent).split('\n').slice(0, 150);
  el.textContent = lines.join('\n');
}

// ===== 화면 표시 =====
function setChip(id, s, text) {
  const el = $(id);
  el.dataset.s = s;
  el.lastElementChild.textContent = text;
}

let connState = 'off';
function setConn(s) {
  connState = s;
  const text = { off: '연결 안 됨', wait: '연결 중…', on: '연결됨', lost: '끊김 · 다시 연결 중' }[s];
  setChip('conn', s, text);
  const on = s === 'on';
  $('btnConnect').textContent = s === 'off' ? '연결' : '연결 끊기';
  $('btnStart').disabled = !on || recording;
  $('btnStop').disabled = !recording;
}

function setSensor(name, v) {
  const map = { ppg: ['sPpg', 'PPG'], imu: ['sImu', 'IMU'], temp: ['sTemp', '온도'] };
  if (!map[name]) return;
  const [id, label] = map[name];
  setChip(id, v === 'ok' ? 'ok' : v === 'lost' ? 'lost' : 'unknown',
          label + ' ' + (v === 'ok' ? '정상' : v === 'lost' ? '끊김' : '-'));
}

function fmtTime(ms) {
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

function updateStats() {
  $('stats').textContent =
    `수신 ${recording ? rxHz : '-'} Hz · 샘플 ${rec.n.toLocaleString()} · 빠진 패킷 ${gaps}` +
    ` · 화면 켜짐 유지 ${wakeLock ? '켜짐' : '꺼짐'}`;
}

// ===== BLE 연결 =====
async function connect() {
  try {
    device = await navigator.bluetooth.requestDevice({
      filters: [{ name: 'RunBand' }],
      optionalServices: [UUID.NUS_SVC, UUID.DATA_SVC],
    });
  } catch (e) {
    if (e.name !== 'NotFoundError') log('연결 취소/실패: ' + e.message);   // NotFoundError = 선택 창 닫음
    return;
  }
  device.ongattserverdisconnected = onDisconnected;   // 같은 기기를 다시 골라도 한 번만
  userClosed = false;
  try {
    await openGatt();
  } catch (e) {
    log('연결 실패: ' + e.message);
    scheduleReconnect();
  }
}

async function openGatt() {
  setConn('wait');
  const server = await device.gatt.connect();
  const nus = await server.getPrimaryService(UUID.NUS_SVC);
  rxChar = await nus.getCharacteristic(UUID.NUS_RX);
  const tx = await nus.getCharacteristic(UUID.NUS_TX);
  const dataSvc = await server.getPrimaryService(UUID.DATA_SVC);
  const data = await dataSvc.getCharacteristic(UUID.DATA_CHR);
  tx.oncharacteristicvaluechanged = onText;     // 다시 연결해도 중복 등록 안 되게 대입
  data.oncharacteristicvaluechanged = onData;
  textBuf = '';
  await tx.startNotifications();
  await data.startNotifications();
  setConn('on');
  log('연결됨: ' + device.name);
  send('STATUS');
  clearInterval(pollTimer);
  pollTimer = setInterval(() => send('STATUS'), 5000);   // 센서 상태 확인
}

function onDisconnected() {
  rxChar = null;
  clearInterval(pollTimer);
  if (userClosed) { setConn('off'); log('연결 끊음'); return; }
  setConn('lost');
  log('연결 끊김 → 다시 연결 시도');
  scheduleReconnect();
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(async () => {
    if (userClosed || !device) return;
    try { await openGatt(); }
    catch (e) { setConn('lost'); scheduleReconnect(); }
  }, 2000);
}

function disconnect() {
  if (recording && !confirm('측정 중이에요. 연결을 끊으면 이후 데이터는 받지 못해요. 끊을까요?')) return;
  userClosed = true;
  clearTimeout(reconnectTimer);
  if (device && device.gatt.connected) device.gatt.disconnect();
  else setConn('off');
}

// 명령은 하나씩 차례로 (동시에 쓰면 GATT 오류)
let writeChain = Promise.resolve();
const enc = new TextEncoder();
function send(cmd) {
  writeChain = writeChain
    .then(() => {
      if (!rxChar) throw new Error('미연결');
      return rxChar.writeValueWithResponse(enc.encode(cmd + '\n'));
    })
    .catch(e => log(`명령 실패 (${cmd}): ${e.message}`));
  return writeChain;
}

// ===== 받은 텍스트 =====
let textBuf = '';
const dec = new TextDecoder();
function onText(e) {
  textBuf += dec.decode(e.target.value, { stream: true });
  let i;
  while ((i = textBuf.indexOf('\n')) >= 0) {
    const line = textBuf.slice(0, i).trim();
    textBuf = textBuf.slice(i + 1);
    if (line) handleLine(line);
  }
}

function handleLine(line) {
  const kv = Protocol.parseKV(line);
  if (line.startsWith('STATUS')) {
    setSensor('ppg', kv.ppg); setSensor('imu', kv.imu); setSensor('temp', kv.temp);
    if (!recording && kv.temp_c && kv.temp_c !== '-') $('temp').textContent = (+kv.temp_c).toFixed(1);
    if (kv.state === 'RUN' && !recording) {
      log('보드가 이미 측정 중 → 이어서 기록');
      beginRecording(true);
    } else if (kv.state === 'IDLE' && recording) {
      log('보드가 측정 중이 아님 (전원이 꺼졌다 켜졌을 수 있음)');
      endRecording('보드가 중간에 멈춤');
    }
    return;
  }
  log(line);
  if (line === 'OK START') beginRecording(false);
  else if (line.startsWith('OK STOP')) endRecording(`보드: ${kv.n}개 만듦, ${kv.sent}개 보냄`);
  else if (line.startsWith('EVT ')) {
    const [k, v] = line.slice(4).split('=');
    setSensor(k, v);
  } else if (line.startsWith('TEMP')) {
    rec.temps.push([+kv.t_ms, kv.c]);
    $('temp').textContent = (+kv.c).toFixed(1);
  }
}

// ===== 받은 데이터 (바이너리) =====
function onData(e) {
  const r = Protocol.parsePacket(e.target.value, (t, red, ir, dv, o) => {
    if (recording) rec.push(t, red, ir, dv, o);
    const ax = dv.getInt16(o, true), ay = dv.getInt16(o + 2, true), az = dv.getInt16(o + 4, true);
    live.t.push(t / 1000);
    live.ir.push(ir);
    live.a.push(Math.sqrt(ax * ax + ay * ay + az * az) * A_SCALE);
    lastT = t;
    secCount++;
  });
  if (!r) { log('모르는 패킷 ' + e.target.value.byteLength + '바이트'); return; }
  if (lastSeq !== null) gaps += (r.seq - lastSeq - 1) & 0xFFFF;
  lastSeq = r.seq;
  pkts++;
  if (live.t.length > 2000) for (const k in live) live[k].splice(0, live[k].length - 1400);
}

// ===== 시작 / 멈춤 =====
function beginRecording(resumed) {
  if (!resumed) {
    rec.reset();
    lastSeq = null; gaps = 0; pkts = 0;
    for (const k in live) live[k].length = 0;
  }
  if (!rec.startedAt) rec.startedAt = new Date();
  recording = true;
  savedData = false;
  $('save').hidden = true;
  $('elapsedSub').textContent = '측정 중';
  setConn(rxChar ? 'on' : 'lost');
  keepAwake(true);
}

function endRecording(note) {
  recording = false;
  keepAwake(false);
  $('elapsedSub').textContent = '멈춤';
  $('hrSub').textContent = $('cadSub').textContent = ' ';
  setConn(rxChar ? 'on' : (userClosed ? 'off' : 'lost'));
  if (rec.n) {
    const dur = rec.n > 1 ? fmtTime(lastT - rec.chunks[0].t[0]) : '0:00';
    $('saveInfo').textContent =
      `샘플 ${rec.n.toLocaleString()}개 (${dur}) · 온도 ${rec.temps.length}개 · 빠진 패킷 ${gaps}` +
      (note ? ` · ${note}` : '');
    $('save').hidden = false;
  }
}

function onStart() {
  if (rec.n && !savedData && !confirm('저장하지 않은 기록이 있어요. 지우고 새로 시작할까요?')) return;
  keepAwake(true);          // 버튼 누를 때 바로 요청
  send('START');
}

function onStop() {
  if (!rxChar) {
    if (confirm('보드와 연결이 끊겨 있어요. 이 화면의 기록만 끝낼까요? (보드는 계속 측정 중일 수 있음)')) {
      endRecording('연결 끊긴 상태에서 멈춤');
    }
    return;
  }
  send('STOP');
}

// ===== CSV 저장 =====
function stamp(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

function download(name, parts) {
  const url = URL.createObjectURL(new Blob(parts, { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function saveData() {
  const base = 'runband_' + stamp(rec.startedAt || new Date());
  download(base + '.csv', rec.dataCsvParts());
  savedData = true;
  log('저장: ' + base + '.csv');
}

function saveTemp() {
  const base = 'runband_' + stamp(rec.startedAt || new Date());
  download(base + '_temp.csv', [rec.tempCsv()]);
  log('저장: ' + base + '_temp.csv');
}

// ===== 화면 꺼짐 방지 =====
let wakePending = false;   // 요청이 겹치면 하나가 안 풀림
async function keepAwake(on) {
  try {
    if (on && !wakeLock && !wakePending && 'wakeLock' in navigator && document.visibilityState === 'visible') {
      wakePending = true;
      try {
        wakeLock = await navigator.wakeLock.request('screen');
      } finally {
        wakePending = false;
      }
      wakeLock.addEventListener('release', () => { wakeLock = null; updateStats(); });
    } else if (!on && wakeLock) {
      await wakeLock.release();
      wakeLock = null;
    }
  } catch (e) {
    log('화면 켜짐 유지 실패: ' + e.message);
  }
  updateStats();
}
// 다른 앱을 갔다 오면 풀리므로 다시 요청
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && recording) keepAwake(true);
});

// ===== 심박 · 케이던스 (2초마다) =====
function median(x) {
  const s = [...x].sort((a, b) => a - b);
  return s[s.length >> 1];
}

function analyze() {
  if (!recording || !live.t.length) return;
  const tEnd = live.t[live.t.length - 1];
  let i0 = live.t.length - 1;
  while (i0 > 0 && live.t[i0 - 1] > tEnd - HR_WIN) i0--;
  const t = live.t.slice(i0), ir = live.ir.slice(i0), a = live.a.slice(i0);
  if (t.length < 2 || t[t.length - 1] - t[0] < HR_WIN * 0.8) {
    $('hrSub').textContent = $('cadSub').textContent = '데이터 모으는 중';
    return;
  }
  const fs = (t.length - 1) / (t[t.length - 1] - t[0]);
  const imuDead = a.every(v => v === 0);

  // 심박
  if (median(ir) < 50000) {                    // hr_filter.py와 같은 기준
    $('hr').textContent = '--';
    $('hrSub').textContent = '피부 접촉 확인';
  } else {
    const r = Analysis.heartRate(ir, a, fs);
    $('hr').textContent = r ? Math.round(r.hr) : '--';
    $('hrSub').textContent = !r ? '봉우리 없음'
      : r.action === '교체' ? `흔들림 리듬 피함 (FFT ${Math.round(r.hrFft)})`
      : r.action === '대체없음' ? '흔들림과 겹침 · 부정확할 수 있음'
      : Number.isNaN(r.motion) ? '움직임 적음' : '흔들림과 무관';
  }

  // 케이던스
  if (imuDead) {
    $('cad').textContent = '--';
    $('cadSub').textContent = 'IMU 끊김';
  } else {
    const c = Analysis.cadence(t, a);
    $('cad').textContent = c ? Math.round(c.spm) : '--';
    $('cadSub').textContent = c ? `최근 ${HR_WIN}초 걸음 ${c.steps}개` : '걸음 없음';
  }

  // 온도 안정 안내
  if (rec.temps.length) {
    const min = (lastT - rec.temps[0][0]) / 60000;
    $('tempSub').textContent = min < STATIC_MIN ? `안정까지 약 ${Math.ceil(STATIC_MIN - min)}분` : '안정 구간';
  }
}

// ===== 그래프 (0.1초마다) =====
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function fitCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  return dpr;
}

// xs: 초, ys: 값. ref가 있으면 그 높이에 점선
function drawLine(cv, xs, ys, color, { minSpan = 0, ref = null } = {}) {
  const dpr = fitCanvas(cv), ctx = cv.getContext('2d'), W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  if (xs.length < 2) return;
  const x1 = xs[xs.length - 1], x0 = x1 - GRAPH_SEC;
  let lo = Infinity, hi = -Infinity;
  for (const v of ys) { if (v < lo) lo = v; if (v > hi) hi = v; }
  if (ref !== null) { lo = Math.min(lo, ref); hi = Math.max(hi, ref); }
  if (hi - lo < minSpan) { const m = (hi + lo) / 2; lo = m - minSpan / 2; hi = m + minSpan / 2; }
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const X = x => (x - x0) / GRAPH_SEC * W, Y = y => H - (y - lo) / (hi - lo) * H;

  if (ref !== null) {
    ctx.strokeStyle = css('--line');
    ctx.lineWidth = 1 * dpr;
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.beginPath(); ctx.moveTo(0, Y(ref)); ctx.lineTo(W, Y(ref)); ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 2 * dpr;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  for (let i = 0; i < xs.length; i++) {
    if (i === 0) ctx.moveTo(X(xs[i]), Y(ys[i])); else ctx.lineTo(X(xs[i]), Y(ys[i]));
  }
  ctx.stroke();
}

function draw() {
  $('elapsed').textContent = fmtTime(recording || rec.n ? lastT : 0);
  if (!live.t.length || document.visibilityState !== 'visible') return;
  const tEnd = live.t[live.t.length - 1];
  let i0 = live.t.length - 1;
  while (i0 > 0 && live.t[i0 - 1] > tEnd - GRAPH_SEC - 1) i0--;   // 1초 더 (평균용)
  const t = live.t.slice(i0), ir = live.ir.slice(i0), a = live.a.slice(i0);

  // PPG: 1초 이동평균을 빼고 뒤집어 맥박이 위로 (hr_compare.py와 같은 모양), 0.1초로 부드럽게
  const n1 = 100, n2 = 10, len = ir.length;
  const pulse = new Array(len), smooth = new Array(len);
  let s1 = 0, s2 = 0;
  for (let i = 0; i < len; i++) {
    s1 += ir[i]; if (i >= n1) s1 -= ir[i - n1];
    pulse[i] = -(ir[i] - s1 / Math.min(i + 1, n1));
    s2 += pulse[i]; if (i >= n2) s2 -= pulse[i - n2];
    smooth[i] = s2 / Math.min(i + 1, n2);
  }
  const k = t.findIndex(x => x >= tEnd - GRAPH_SEC);
  drawLine($('cvPpg'), t.slice(k), smooth.slice(k), css('--series-1'), { minSpan: 50 });
  drawLine($('cvAcc'), t.slice(k), a.slice(k), css('--series-2'), { minSpan: 0.5, ref: 1 });
}

// ===== 시작 =====
if (!navigator.bluetooth) {
  $('unsupported').hidden = false;
  $('btnConnect').disabled = true;
}
$('btnConnect').onclick = () => (connState === 'off' ? connect() : disconnect());
$('btnStart').onclick = onStart;
$('btnStop').onclick = onStop;
$('btnCsv').onclick = saveData;
$('btnTempCsv').onclick = saveTemp;
window.addEventListener('beforeunload', e => {
  if (recording || (rec.n && !savedData)) { e.preventDefault(); e.returnValue = ''; }
});

setInterval(() => { rxHz = secCount; secCount = 0; updateStats(); }, 1000);
setInterval(analyze, 2000);
setInterval(draw, 100);
setConn('off');
updateStats();
