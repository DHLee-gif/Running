"""
RunBand 기록 → 한 장짜리 PNG (심박 · 케이던스 · 피부 온도 · IR)

- 심박은 웹(web/analysis.js)과 같은 방식: 걸음 없으면 기존 방식, 걸으면 팔 흔들기 리듬 빼고 추적,
  달리기(케이던스 130 이상)나 심박≈케이던스(±10)는 흐리게 (부정확)
- 배경 음영: 정지 / 걷기 / 달리기 (케이던스로 구분)
- 워치 값이 있으면 점으로 같이 그림 (--watch, --test, --watch-start)

사용법:
    python tools/plot/runband_plot.py data/runband_20261024_2350.csv
    python tools/plot/runband_plot.py --all                    # data/의 모든 기록
    python tools/plot/runband_plot.py data/runband_20261024_2350.csv \\
        --watch data/watch_20261025.csv --test first --watch-start 9.78
결과: 같은 폴더에 runband_..._plot.png
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import step_detect as sd  # noqa: E402  (기존 걸음 규칙 v2 그대로 사용)

parser = argparse.ArgumentParser()
parser.add_argument("csv", nargs="?", type=Path)
parser.add_argument("--all", action="store_true", help="data/의 runband_*.csv 전부")
parser.add_argument("--watch", type=Path, help="워치 값 CSV (test,watch_min,bpm)")
parser.add_argument("--test", help="워치 CSV에서 쓸 test 이름 (예: first)")
parser.add_argument("--watch-start", type=float, help="워치 0분이 기록의 몇 분인지")
parser.add_argument("--step", type=float, default=2, help="계산 간격 (초)")
args = parser.parse_args()

# ===== 색 (밝은 배경, 역할별 하나씩) =====
C_HR, C_CAD, C_TEMP, C_IR, C_WATCH = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e34948"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e1e0d9"
PHASE = {"정지": None, "걷기": "#f1f0ec", "달리기": "#e3e2dc"}
plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2})

# ===== 심박 계산 (web/analysis.js와 같은 규칙) =====
HR_BAND, MOTION_BAND, LOCK, MINREL, AMOV_MIN = (50, 200), (48, 220), 6, 0.15, 0.02
RUN_CAD, ARM_LOCK, OVERLAP = 130, 7, 10


def spectrum(x, fs, pad=8):
    n = len(x)
    x = x - np.polyval(np.polyfit(np.arange(n), x, 1), np.arange(n))
    nfft = int(2 ** np.ceil(np.log2(n * pad)))
    mag = np.abs(np.fft.rfft(x * np.hanning(n), nfft))
    return np.fft.rfftfreq(nfft, 1 / fs) * 60, mag


def peaks(bpm, mag, lo, hi):
    idx = [i for i in range(1, len(mag) - 1)
           if lo <= bpm[i] <= hi and mag[i] > mag[i - 1] and mag[i] >= mag[i + 1]]
    idx.sort(key=lambda i: -mag[i])
    return [(bpm[i], mag[i]) for i in idx]


def hr_still(c, a, fs):
    """기존 방식 (hr_filter.py 규칙)"""
    hf = c[0][0]
    if np.std(a) >= AMOV_MIN:
        mp = peaks(*spectrum(a, fs), *MOTION_BAND)
        if mp:
            m = mp[0][0]
            base = m / 2 if m >= 70 else m
            bad = [base * k for k in range(1, 7)]
            k = [x for x in c if all(abs(x[0] - b) > LOCK for b in bad)]
            k = [x for x in k if all(abs(x[0] - 2 * y[0]) > LOCK for y in c)]
            k = [x for x in k if x[1] >= MINREL * c[0][1]]
            if k:
                return k[0][0]
    return hf


def cadence(t, a, fs):
    steps, _ = sd.detect_steps(t, a, fs, sd.V2)
    _, iv = sd.step_intervals(t, steps, sd.V2["max_interval"])
    iv = sd.drop_outliers(iv)
    return 60 / np.median(iv) if len(iv) >= 3 else None


def analyze(t, ir, a, fs, step):
    """10초 구간을 step초마다: (시각, 심박, 부정확 여부, 케이던스)"""
    times = np.arange(10, t[-1], step)
    hr, low, cads = [], [], []
    prev = None
    i0 = i1 = 0
    for T in times:
        while i1 < len(t) and t[i1] <= T:
            i1 += 1
        while i0 < i1 and t[i0] <= T - 10:
            i0 += 1
        tw, iw, aw = t[i0:i1], ir[i0:i1], a[i0:i1]
        c = peaks(*spectrum(iw, fs), *HR_BAND)
        cad = cadence(tw, aw, fs)
        if not c:
            hr.append(np.nan); low.append(True); cads.append(cad or np.nan)
            continue
        if cad is None:                                   # 걸음 없음
            prev = hr_still(c, aw, fs)
            hr.append(prev); low.append(False); cads.append(np.nan)
            continue
        cc = [x for x in c[:8] if x[1] >= 0.1 * c[0][1]]
        arm = cad / 2
        c2 = [x for x in cc if abs(x[0] - arm) > ARM_LOCK and abs(x[0] - 3 * arm) > ARM_LOCK]
        if c2:
            cc = c2
        if prev is None:
            prev = cc[0][0]
        jump = 40 if prev < cad * 0.6 else 10
        near = [x for x in cc if abs(x[0] - prev) <= jump]
        if near:
            best = max(near, key=lambda x: x[1] / (1 + abs(x[0] - prev) / 5))
            prev = 0.6 * prev + 0.4 * best[0]
        hr.append(prev)
        low.append(cad >= RUN_CAD or abs(prev - cad) <= OVERLAP)
        cads.append(cad)
    return times, np.array(hr), np.array(low), np.array(cads)


def phases(times, cads, min_len=20):
    """케이던스 → (시작초, 끝초, 이름) 구간. 짧은 토막은 앞 구간에 합침"""
    lab = np.where(np.isnan(cads), "정지", np.where(cads >= RUN_CAD, "달리기", "걷기"))
    segs = []
    for T, L in zip(times, lab):
        if segs and segs[-1][2] == L:
            segs[-1][1] = T
        else:
            segs.append([T, T, L])
    merged = []
    for s in segs:
        if merged and (s[1] - s[0] < min_len):
            merged[-1][1] = s[1]                          # 짧으면 앞 구간에 붙임
        elif merged and merged[-1][2] == s[2]:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return merged


def masked(y, mask):
    out = y.astype(float).copy()
    out[~mask] = np.nan
    return out


def plot(csv: Path):
    d = pd.read_csv(csv)
    t = d.t_ms.to_numpy() / 1000
    fs = (len(d) - 1) / (t[-1] - t[0])
    ir = d.ir.to_numpy(float)
    a = np.sqrt(d.ax ** 2 + d.ay ** 2 + d.az ** 2).to_numpy()
    gaps = np.diff(d.t_ms.to_numpy())
    gap_s = gaps[gaps > 50].sum() / 1000
    temp_path = csv.with_name(csv.stem + "_temp.csv")
    temp = pd.read_csv(temp_path) if temp_path.exists() else None

    print(f"{csv.name}: {len(d)}개, {t[-1] / 60:.1f}분 계산 중...")
    times, hr, low, cads = analyze(t, ir, a, fs, args.step)
    segs = phases(times, cads)
    m = times / 60

    # ----- 요약 -----
    dur = {k: sum(e - s for s, e, L in segs if L == k) / 60 for k in PHASE}
    def med(mask, y):
        v = y[mask & ~np.isnan(y)]
        return f"{np.median(v):.0f}" if len(v) else "-"
    still = np.isnan(cads)
    run = cads >= RUN_CAD
    walk = (cads < RUN_CAD) & ~still
    summary = (f"{csv.stem}   ·   {t[-1] / 60:.1f}분, {fs:.1f} Hz, 빠진 구간 {gap_s:.1f}초   ·   "
               f"정지 {dur['정지']:.1f}분 / 걷기 {dur['걷기']:.1f}분 / 달리기 {dur['달리기']:.1f}분\n"
               f"정지 심박 중앙값 {med(still, hr)} bpm   ·   케이던스 중앙값 걷기 {med(walk, cads)}, "
               f"달리기 {med(run, cads)} spm")
    if temp is not None:
        summary += f"   ·   피부 온도 {temp.temp.min():.1f}~{temp.temp.max():.1f}℃"

    # ----- 그림 -----
    fig, axes = plt.subplots(4, 1, figsize=(13, 10), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2, 1.6, 1.2], "hspace": 0.12})
    fig.patch.set_facecolor("white")
    fig.suptitle(summary, x=0.06, y=0.985, ha="left", va="top", fontsize=11, color=INK)

    for ax in axes:
        ax.set_facecolor("white")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        for s, e, L in segs:
            if PHASE[L]:
                ax.axvspan(s / 60, e / 60, color=PHASE[L], zorder=0, linewidth=0)
    for s, e, L in segs:                                   # 구간 이름은 맨 위 칸에
        if (e - s) >= 40:
            axes[0].text((s + e) / 120, 1.01, L, transform=axes[0].get_xaxis_transform(),
                         ha="center", va="bottom", fontsize=10, color=INK2)

    # 1) 심박
    ax = axes[0]
    ax.plot(m, masked(hr, ~low), color=C_HR, linewidth=2, label="센서 심박")
    ax.plot(m, masked(hr, low), color=C_HR, linewidth=2, alpha=0.3, label="센서 심박 (부정확)")
    if args.watch and args.test and args.watch_start is not None:
        w = pd.read_csv(args.watch)
        w = w[w.test == args.test]
        ax.plot(args.watch_start + w.watch_min, w.bpm, "o", color=C_WATCH, markersize=6,
                markeredgecolor="white", markeredgewidth=1.5, label="워치", zorder=5)
    ax.set_ylabel("심박 (bpm)")
    ax.set_ylim(40, 200)
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=3)

    # 2) 케이던스
    ax = axes[1]
    ax.plot(m, cads, color=C_CAD, linewidth=2)
    ax.set_ylabel("케이던스 (spm)")
    ax.set_ylim(0, max(200, np.nanmax(cads) + 10) if np.any(~np.isnan(cads)) else 200)

    # 3) 피부 온도
    ax = axes[2]
    if temp is not None and len(temp):
        ax.plot(temp.t_ms / 60000, temp.temp, color=C_TEMP, linewidth=2)
        lo, hi = temp.temp.min(), temp.temp.max()
        ax.set_ylim(lo - 0.5, hi + 0.5)
    else:
        ax.text(0.5, 0.5, "온도 파일 없음", transform=ax.transAxes, ha="center", color=INK2)
    ax.set_ylabel("피부 온도 (℃)")

    # 4) IR (1초 평균) — 접촉 상태
    ax = axes[3]
    n = max(1, int(fs))
    ir_s = pd.Series(ir).rolling(n, center=True, min_periods=1).mean().to_numpy()[::n]
    ax.plot(t[::n] / 60, ir_s / 1000, color=C_IR, linewidth=1.5)
    ax.axhline(50, color=C_WATCH, linewidth=1, linestyle=":")
    ax.text(0.005, 50, " 50k 미만 = 접촉 끊김", transform=ax.get_yaxis_transform(),
            va="bottom", fontsize=8, color=INK2)
    ax.set_ylabel("IR (천)")
    ax.set_ylim(0, max(260, np.nanmax(ir_s) / 1000 * 1.1))
    ax.set_xlabel("시간 (분)")
    ax.set_xlim(0, t[-1] / 60)

    out = csv.with_name(csv.stem + "_plot.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"  저장: {out}")


if args.all:
    files = sorted(p for p in (REPO / "data").glob("runband_*.csv")
                   if not p.stem.endswith(("_temp", "_plot")))
elif args.csv:
    files = [args.csv]
else:
    parser.error("CSV 경로나 --all 을 주세요")
for f in files:
    plot(f)
