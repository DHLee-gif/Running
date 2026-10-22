"""
IMU 걸음 리듬으로 가짜 심박 거르기 (거르기 전/후 비교)

각 시점(15·30·45·60초) 직전 --win초 구간마다:
    ① PPG(IR)의 주파수 성분에서 심박 후보(봉우리)를 찾는다 (--band, 기본 55~150 bpm)
    ② 같은 구간 IMU |a|에서 흔들림 리듬을 찾고, 팔 흔들기 리듬(기본 리듬)을 정한다
    ③ 기본 리듬의 1~6배에서 ±--lock bpm 안의 후보, 다른 후보의 2배(배음), 약한 후보는 버린다
    ④ 남은 후보 중 가장 강한 것 = 심박 (남은 게 없으면 거르기 전 값)

비교하는 세 가지:
    beat : 기존 방법 (박동 봉우리 간격, hr_compare.py와 같음)
    fft  : 주파수 방법, 거르기 전 (가장 강한 후보)
    filt : 주파수 방법, IMU로 거른 후

사용법: python tools/hr_filter.py
결과:   data/hr_filter.csv, data/hr_filter.png
"""
import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--trials", default="data/hr_trials.csv")
parser.add_argument("--win", type=float, default=10, help="각 시점 직전 몇 초를 쓸지")
parser.add_argument("--skip", type=float, default=3, help="앞에서 버릴 시간 (초)")
parser.add_argument("--lock", type=float, default=6, help="흔들림 리듬과 이 bpm 이내인 후보는 버림")
parser.add_argument("--band", type=float, nargs=2, default=[55, 150],
                    help="심박 후보 범위 (bpm). 제자리걸음이면 55~150이면 충분")
parser.add_argument("--still", type=float, default=0.0,
                    help="|a| 표준편차가 이 값(g)보다 작으면 흔들림이 약하다고 보고 거르지 않음 (0이면 항상 거름)")
parser.add_argument("--minrel", type=float, default=0.15, help="가장 큰 후보의 이 비율보다 약한 후보는 잡음으로 봄")
args = parser.parse_args()

POINTS = [15, 30, 45, 60]
HR_BAND = tuple(args.band)     # 심박 후보 범위 (bpm)
data_dir = os.path.dirname(args.trials) or "."


# ===== 공통 도구 =====
def moving_average(x, n):
    return np.convolve(x, np.ones(n) / n, mode="same")


def spectrum(x, fs, pad=8):
    """선형 추세를 빼고 Hann 창을 씌운 주파수 성분. (bpm 축, 크기)
    pad: 0을 덧붙여 눈금을 촘촘하게 (해상도 자체가 좋아지진 않음)"""
    n = len(x)
    x = x - np.polyval(np.polyfit(np.arange(n), x, 1), np.arange(n))
    nfft = int(2 ** np.ceil(np.log2(n * pad)))
    mag = np.abs(np.fft.rfft(x * np.hanning(n), nfft))
    bpm = np.fft.rfftfreq(nfft, 1 / fs) * 60
    return bpm, mag


def peaks_in_band(bpm, mag, lo, hi):
    """lo~hi bpm 안의 봉우리들 (bpm, 크기), 큰 순서."""
    idx = [i for i in range(1, len(mag) - 1)
           if lo <= bpm[i] <= hi and mag[i] > mag[i - 1] and mag[i] >= mag[i + 1]]
    idx.sort(key=lambda i: -mag[i])
    return [(bpm[i], mag[i]) for i in idx]


def find_beats(t, x, height, min_interval=0.33):
    beats, last_t = [], -1e9
    for i in range(1, len(x) - 1):
        if not (x[i] > x[i - 1] and x[i] >= x[i + 1]) or x[i] < height:
            continue
        if t[i] - last_t < min_interval:
            if beats and x[i] > x[beats[-1]]:
                beats[-1] = i
                last_t = t[i]
            continue
        beats.append(i)
        last_t = t[i]
    return np.array(beats, dtype=int)


def usable_start(t, ir):
    """손가락이 안 닿은 구간(ir < 5만)이 앞쪽에 있으면 그 뒤 1.5초부터 사용."""
    start = args.skip
    off = np.where((ir < 50000) & (t < 15))[0]
    if len(off):
        start = max(start, t[off[-1]] + 1.5)
    return start


def beat_times(t, ir, fs, start):
    """기존 방법 (hr_compare.py와 동일)."""
    pulse = -(ir - moving_average(ir, int(fs)))
    pulse = moving_average(pulse, max(1, int(fs * 0.1)))
    keep = np.zeros(len(t), bool)
    keep[int(fs):-int(fs)] = True
    keep &= t >= start
    tk, pk = t[keep], pulse[keep]
    return tk[find_beats(tk, pk, 0.5 * np.std(pk))]


# ===== 시점별 계산 =====
trials = pd.read_csv(args.trials, skipinitialspace=True, encoding="utf-8-sig")
rows = []
for _, tr in trials.iterrows():
    df = pd.read_csv(os.path.join(data_dir, str(tr["file"]).strip()))
    t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
    fs = 1000.0 / df["t_ms"].diff().mean()
    ir = df["ir"].to_numpy(float)
    mag = np.sqrt(df["ax"] ** 2 + df["ay"] ** 2 + df["az"] ** 2).to_numpy()
    start = usable_start(t, ir)
    bt = beat_times(t, ir, fs, start)

    for T in POINTS:
        watch = tr.get(f"w{T}")
        w = (t > max(T - args.win, start)) & (t <= T)

        # 기존 방법
        b = bt[(bt > T - args.win) & (bt <= T)]
        hr_beat = 60 / np.median(np.diff(b)) if len(b) >= 3 else np.nan

        # 주파수 방법: 심박 후보
        bpm, spec = spectrum(ir[w], fs)
        cands = peaks_in_band(bpm, spec, *HR_BAND)
        hr_fft = cands[0][0] if cands else np.nan

        # IMU 흔들림 리듬 (거의 안 움직이면 없음)
        motion = np.nan
        amov = np.std(mag[w])                       # 흔들림 세기 (g)
        if amov >= 0.02:
            mb, ms = spectrum(mag[w], fs)
            mp = peaks_in_band(mb, ms, 48, 180)
            motion = mp[0][0] if mp else np.nan

        # 거르기: 팔 흔들기 리듬(기본 리듬)의 1~6배 근처 후보 버리기
        #   IMU가 걸음(70 이상)을 잡았으면 팔 리듬 = 걸음/2, 팔(70 미만)을 잡았으면 그대로
        #   예) 걸음 80 → 팔 40 → 40, 80, 120, 160 ... 모두 흔들림 리듬
        hr_filt, action = hr_fft, "-"
        if amov < args.still:
            action = "약함"                                  # 흔들림이 약해서 거르지 않음
        elif not np.isnan(motion):
            base = motion / 2 if motion >= 70 else motion
            bad = [base * k for k in range(1, 7)]
            keep_c = [c for c in cands if all(abs(c[0] - m) > args.lock for m in bad)]
            # 남은 후보가 다른 후보의 2배(배음)이면 진짜 심박이 아님 → 버림
            keep_c = [c for c in keep_c
                      if all(abs(c[0] - 2 * d[0]) > args.lock for d in cands)]
            # 너무 약한 후보는 잡음 → 버림
            keep_c = [c for c in keep_c if c[1] >= args.minrel * cands[0][1]]
            if not keep_c:
                hr_filt, action = hr_fft, "대체없음"          # 남은 후보가 없으면 거르기 전 값 유지
            elif keep_c[0][0] != hr_fft:
                hr_filt, action = keep_c[0][0], "교체"        # 흔들림 후보를 버리고 다른 후보 선택
            else:
                hr_filt, action = hr_fft, "유지"              # 가장 강한 후보가 흔들림과 무관

        err = lambda h: round(h - watch, 1) if pd.notna(watch) and not np.isnan(h) else np.nan
        rows.append({"file": tr["file"], "arm": tr["arm"], "spm": tr["spm"], "t": T,
                     "motion": round(motion, 1) if not np.isnan(motion) else np.nan,
                     "amov": round(amov, 3),
                     "watch": watch,
                     "beat": round(hr_beat, 1), "fft": round(hr_fft, 1), "filt": round(hr_filt, 1), "action": action,
                     "err_beat": err(hr_beat), "err_fft": err(hr_fft), "err_filt": err(hr_filt)})

res = pd.DataFrame(rows)
out_csv = os.path.join(data_dir, "hr_filter.csv")
res.to_csv(out_csv, index=False, encoding="utf-8-sig")

pd.set_option("display.width", 140)
print(res.drop(columns=["err_beat", "err_fft", "err_filt"]).to_string(index=False))

mae = res.groupby("file", sort=False).agg(
    arm=("arm", "first"),
    beat=("err_beat", lambda e: e.abs().mean()),
    fft=("err_fft", lambda e: e.abs().mean()),
    filt=("err_filt", lambda e: e.abs().mean()))
print("\n===== 조건별 평균 절대 오차 (bpm) =====")
print(mae.round(1).to_string())
for arm in ["A", "B"]:
    m = mae[mae["arm"] == arm][["beat", "fft", "filt"]].mean()
    print(f"{arm} 평균: beat {m['beat']:.1f} / fft {m['fft']:.1f} / filt {m['filt']:.1f}")

# ===== 그래프 =====
fig, ax = plt.subplots(figsize=(12, 5))
x = np.arange(len(mae))
for k, (col, c) in enumerate([("beat", "gray"), ("fft", "tab:orange"), ("filt", "tab:green")]):
    ax.bar(x + (k - 1) * 0.27, mae[col], 0.27, color=c,
           label={"beat": "beat (peaks)", "fft": "FFT (before)", "filt": "FFT + IMU filter"}[col])
ax.set_xticks(x)
ax.set_xticklabels([f.replace("hr_", "").replace(".csv", "") for f in mae.index])
ax.set_ylabel("mean |sensor - watch| (bpm)")
ax.set_title("Error before / after IMU filtering")
ax.legend()
ax.grid(alpha=0.3, axis="y")
plt.tight_layout()
out_png = os.path.join(data_dir, "hr_filter.png")
plt.savefig(out_png, dpi=120)
print(f"\n표 저장: {out_csv}\n그래프 저장: {out_png}")
plt.show()