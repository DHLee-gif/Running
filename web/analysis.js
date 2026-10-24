// 심박 · 케이던스 계산
// 규칙은 tools/hr_filter.py(심박)와 tools/step_detect.py v2(걸음)를 그대로 옮김
const Analysis = (() => {
  const HR_BAND = [50, 200];      // 심박 후보 범위 (bpm). 달리기라 hr_filter 기본 55~150보다 넓힘
  const MOTION_BAND = [48, 220];  // 흔들림 리듬 범위. 달리기 걸음(~190)까지
  const LOCK = 6;                 // 흔들림 리듬과 이 bpm 이내인 후보는 버림
  const MINREL = 0.15;            // 가장 큰 후보의 이 비율보다 약하면 잡음
  const AMOV_MIN = 0.02;          // |a| 표준편차(g)가 이보다 작으면 흔들림 없음
  const STEP = { threshold: 1.15, minInterval: 0.3, maxInterval: 2.0, confirmN: 4, adaptive: 0.4 };

  // ===== 공통 도구 =====
  function fft(re, im) {          // 제자리 radix-2 FFT (길이는 2의 거듭제곱)
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        [re[i], re[j]] = [re[j], re[i]];
        [im[i], im[j]] = [im[j], im[i]];
      }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang), h = len >> 1;
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let k = 0; k < h; k++) {
          const a = i + k, b = a + h;
          const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
          re[b] = re[a] - tr; im[b] = im[a] - ti;
          re[a] += tr;        im[a] += ti;
          const nr = cr * wr - ci * wi;
          ci = cr * wi + ci * wr;
          cr = nr;
        }
      }
    }
  }

  // 선형 추세 빼고 Hann 창, 0 덧붙여 8배 촘촘하게 → {bpm, mag}
  function spectrum(x, fs, pad = 8) {
    const n = x.length;
    let sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) { sx += i; sy += x[i]; sxx += i * i; sxy += i * x[i]; }
    const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx);
    const icpt = (sy - slope * sx) / n;
    const nfft = 2 ** Math.ceil(Math.log2(n * pad));
    const re = new Float64Array(nfft), im = new Float64Array(nfft);
    for (let i = 0; i < n; i++) {
      const w = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1));
      re[i] = (x[i] - (slope * i + icpt)) * w;
    }
    fft(re, im);
    const half = nfft / 2 + 1;
    const mag = new Float64Array(half), bpm = new Float64Array(half);
    for (let k = 0; k < half; k++) {
      mag[k] = Math.hypot(re[k], im[k]);
      bpm[k] = k * fs / nfft * 60;
    }
    return { bpm, mag };
  }

  // lo~hi 안의 봉우리들 [bpm, 크기], 큰 순서
  function peaksInBand({ bpm, mag }, [lo, hi]) {
    const out = [];
    for (let i = 1; i < mag.length - 1; i++) {
      if (bpm[i] >= lo && bpm[i] <= hi && mag[i] > mag[i - 1] && mag[i] >= mag[i + 1]) out.push([bpm[i], mag[i]]);
    }
    return out.sort((a, b) => b[1] - a[1]);
  }

  function std(x) {
    const m = x.reduce((s, v) => s + v, 0) / x.length;
    return Math.sqrt(x.reduce((s, v) => s + (v - m) ** 2, 0) / x.length);
  }

  function median(x) {
    const s = [...x].sort((a, b) => a - b), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  // ===== 심박: FFT + IMU 리듬 거르기 =====
  // ir, amag: 같은 길이 (최근 10초), fs: Hz
  function heartRate(ir, amag, fs) {
    const cands = peaksInBand(spectrum(ir, fs), HR_BAND);
    if (!cands.length) return null;
    const hrFft = cands[0][0];

    // IMU 흔들림 리듬 (거의 안 움직이면 없음)
    const amov = std(amag);
    let motion = NaN;
    if (amov >= AMOV_MIN) {
      const mp = peaksInBand(spectrum(amag, fs), MOTION_BAND);
      if (mp.length) motion = mp[0][0];
    }

    // 팔 흔들기 리듬(걸음이면 절반)의 1~6배 근처 후보, 배음, 약한 후보 버리기
    let hr = hrFft, action = '-';
    if (!Number.isNaN(motion)) {
      const base = motion >= 70 ? motion / 2 : motion;
      const bad = [1, 2, 3, 4, 5, 6].map(k => base * k);
      let keep = cands.filter(c => bad.every(m => Math.abs(c[0] - m) > LOCK));
      keep = keep.filter(c => cands.every(d => Math.abs(c[0] - 2 * d[0]) > LOCK));
      keep = keep.filter(c => c[1] >= MINREL * cands[0][1]);
      if (!keep.length) action = '대체없음';
      else if (keep[0][0] !== hrFft) { hr = keep[0][0]; action = '교체'; }
      else action = '유지';
    }
    return { hr, hrFft, motion, amov, action };
  }

  // ===== 케이던스: step_detect.py v2 =====
  function findCandidates(t, m) {
    const p = STEP, cands = [], gaps = [];
    let lastT = -1e9;
    for (let i = 1; i < m.length - 1; i++) {
      if (!(m[i] > m[i - 1] && m[i] >= m[i + 1]) || m[i] < p.threshold) continue;
      let gap = p.minInterval;
      const recent = gaps.slice(-5).filter(g => g < 2.0);       // 걷기 사이 공백 제외
      if (p.adaptive > 0 && recent.length >= 3) gap = Math.max(p.minInterval, median(recent) * p.adaptive);
      if (t[i] - lastT < gap) {                                 // 직전 후보와 너무 가까움
        if (cands.length && m[i] > m[cands[cands.length - 1]]) { // 더 큰 봉우리면 교체
          if (cands.length >= 2) gaps[gaps.length - 1] = t[i] - t[cands[cands.length - 2]];
          cands[cands.length - 1] = i;
          lastT = t[i];
        }
        continue;
      }
      if (cands.length) gaps.push(t[i] - lastT);
      cands.push(i);
      lastT = t[i];
    }
    return cands;
  }

  function confirmSteps(t, cands) {   // 연속 confirmN개 이상 이어진 후보만 걸음
    const steps = [];
    let pending = [], walking = false, prevT = null;
    for (const i of cands) {
      if (prevT !== null && t[i] - prevT > STEP.maxInterval) { walking = false; pending = []; }
      prevT = t[i];
      if (walking) steps.push(i);
      else {
        pending.push(i);
        if (pending.length >= STEP.confirmN) { walking = true; steps.push(...pending); pending = []; }
      }
    }
    return steps;
  }

  // t: 초, amag: |a| (g) → {spm, steps} 또는 null
  function cadence(t, amag) {
    const steps = confirmSteps(t, findCandidates(t, amag));
    let iv = [];
    for (let k = 1; k < steps.length; k++) {
      const d = t[steps[k]] - t[steps[k - 1]];
      if (d <= STEP.maxInterval) iv.push(d);
    }
    if (iv.length) {                  // 중앙값의 0.5배 미만 / 1.5배 초과 간격 제외
      const med = median(iv);
      iv = iv.filter(d => d >= med * 0.5 && d <= med * 1.5);
    }
    if (iv.length < 3) return null;
    return { spm: 60 / median(iv), steps: steps.length };
  }

  // ===== 심박 추적기 (2026-10-25 착용 테스트 결과 반영) =====
  // - 걸음 없음: heartRate()(기존 방식)로 계산하고 추적 기준을 그 값으로 다시 맞춤
  // - 걸음 있음: 팔 흔들기 리듬(케이던스/2)과 그 3배 근처 후보를 빼고, 이전 값에서 가깝고 강한 후보를 따라감
  // - 달리기(케이던스 130 이상)나 심박≈케이던스(±10)면 '부정확' (테스트에서 달리기 오차가 컸음)
  const RUN_CAD = 130, ARM_LOCK = 7, OVERLAP = 10;

  function createHrTracker() {
    let prev = null;
    return {
      reset() { prev = null; },
      // t: 초, ir/amag: 최근 10초, fs: Hz → {hr, cad, mode, low}
      update(t, ir, amag, fs) {
        const c0 = cadence(t, amag);
        const cad = c0 ? c0.spm : null;
        if (cad === null) {                                   // 걸음 없음
          const r = heartRate(ir, amag, fs);
          if (!r) return null;
          prev = r.hr;
          return { hr: prev, cad, mode: 'still', low: false };
        }
        const all = peaksInBand(spectrum(ir, fs), HR_BAND);
        if (!all.length) return null;
        let c = all.slice(0, 8).filter(x => x[1] >= 0.1 * all[0][1]);
        const arm = cad / 2;
        const c2 = c.filter(x => Math.abs(x[0] - arm) > ARM_LOCK && Math.abs(x[0] - 3 * arm) > ARM_LOCK);
        if (c2.length) c = c2;
        if (prev === null) prev = c[0][0];
        const jump = prev < cad * 0.6 ? 40 : 10;                // 운동 시작 직후엔 크게 움직일 수 있음
        const near = c.filter(x => Math.abs(x[0] - prev) <= jump);
        if (near.length) {
          let best = near[0], bestScore = -1;
          for (const x of near) {
            const s = x[1] / (1 + Math.abs(x[0] - prev) / 5);  // 가깝고 강한 후보
            if (s > bestScore) { bestScore = s; best = x; }
          }
          prev = 0.6 * prev + 0.4 * best[0];
        }
        const low = cad >= RUN_CAD || Math.abs(prev - cad) <= OVERLAP;
        return { hr: prev, cad, mode: cad >= RUN_CAD ? 'run' : 'walk', low };
      },
    };
  }

  return { heartRate, cadence, spectrum, peaksInBand, createHrTracker };
})();

if (typeof module !== 'undefined') module.exports = Analysis;   // node 테스트용
