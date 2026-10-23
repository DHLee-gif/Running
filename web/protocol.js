// 보드 ↔ 웹 약속 (firmware/runband_ble 와 같게)
const Protocol = (() => {
  const UUID = {
    NUS_SVC:  '6e400001-b5a3-f393-e0a9-e50e24dcca9e',
    NUS_RX:   '6e400002-b5a3-f393-e0a9-e50e24dcca9e',   // 웹 → 보드 (명령)
    NUS_TX:   '6e400003-b5a3-f393-e0a9-e50e24dcca9e',   // 보드 → 웹 (텍스트)
    DATA_SVC: '7a1e0001-5c3b-4f0e-9d2a-6b8f1c2e3d40',
    DATA_CHR: '7a1e0002-5c3b-4f0e-9d2a-6b8f1c2e3d40',   // 보드 → 웹 (바이너리)
  };
  const A_SCALE = 0.000244;   // ±8g    → g
  const G_SCALE = 0.0175;     // ±500dps → dps
  const SAMPLE_BYTES = 22;

  // 패킷 = [0x01][n][seq 2B] + n × (t 4B, red 3B, ir 3B, ax ay az gx gy gz 2B씩)
  // onSample(t, red, ir, dv, imuOffset) 를 샘플마다 호출. 반환: {n, seq} 또는 null
  function parsePacket(dv, onSample) {
    if (dv.byteLength < 4 || dv.getUint8(0) !== 0x01) return null;
    const n = dv.getUint8(1), seq = dv.getUint16(2, true);
    if (dv.byteLength !== 4 + n * SAMPLE_BYTES) return null;
    for (let i = 0, o = 4; i < n; i++, o += SAMPLE_BYTES) {
      const t = dv.getUint32(o, true);
      const red = dv.getUint8(o + 4) | (dv.getUint8(o + 5) << 8) | (dv.getUint8(o + 6) << 16);
      const ir = dv.getUint8(o + 7) | (dv.getUint8(o + 8) << 8) | (dv.getUint8(o + 9) << 16);
      onSample(t, red, ir, dv, o + 10);
    }
    return { n, seq };
  }

  // "STATUS state=RUN t_ms=12 ..." → {state:'RUN', t_ms:'12', ...}
  function parseKV(line) {
    const o = {};
    for (const p of line.split(' ').slice(1)) {
      const i = p.indexOf('=');
      if (i > 0) o[p.slice(0, i)] = p.slice(i + 1);
    }
    return o;
  }

  // ===== 기록 저장소 (1만 샘플씩 묶어 typed array에) =====
  const CHUNK = 10000;
  class Recorder {
    constructor() { this.reset(); }
    reset() {
      this.chunks = [];
      this.cur = null;
      this.n = 0;
      this.temps = [];          // [t_ms, "31.234"]
      this.startedAt = null;    // Date
    }
    push(t, red, ir, dv, o) {
      if (!this.cur || this.cur.n === CHUNK) {
        this.cur = { n: 0, t: new Uint32Array(CHUNK), red: new Uint32Array(CHUNK),
                     ir: new Uint32Array(CHUNK), imu: new Int16Array(CHUNK * 6) };
        this.chunks.push(this.cur);
      }
      const c = this.cur, k = c.n++;
      c.t[k] = t; c.red[k] = red; c.ir[k] = ir;
      for (let j = 0; j < 6; j++) c.imu[k * 6 + j] = dv.getInt16(o + 2 * j, true);
      this.n++;
    }
    // 열은 기존 도구와 같게: t_ms,red,ir,ax,ay,az,gx,gy,gz (가속도 3자리, 자이로 2자리)
    // 긴 기록도 문자열 하나로 합치지 않게 조각 배열로 반환 (Blob에 그대로 넣음)
    dataCsvParts() {
      const parts = ['t_ms,red,ir,ax,ay,az,gx,gy,gz\n'];
      for (const c of this.chunks) {
        const lines = new Array(c.n);
        for (let k = 0; k < c.n; k++) {
          const m = k * 6;
          lines[k] = c.t[k] + ',' + c.red[k] + ',' + c.ir[k] + ',' +
            (c.imu[m] * A_SCALE).toFixed(3) + ',' + (c.imu[m + 1] * A_SCALE).toFixed(3) + ',' +
            (c.imu[m + 2] * A_SCALE).toFixed(3) + ',' + (c.imu[m + 3] * G_SCALE).toFixed(2) + ',' +
            (c.imu[m + 4] * G_SCALE).toFixed(2) + ',' + (c.imu[m + 5] * G_SCALE).toFixed(2);
        }
        if (c.n) parts.push(lines.join('\n') + '\n');
      }
      return parts;
    }
    tempCsv() {
      return 't_ms,temp\n' + this.temps.map(([t, c]) => t + ',' + c + '\n').join('');
    }
  }

  return { UUID, A_SCALE, G_SCALE, SAMPLE_BYTES, parsePacket, parseKV, Recorder };
})();

if (typeof module !== 'undefined') module.exports = Protocol;   // node 테스트용
