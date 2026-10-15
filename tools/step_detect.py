"""
IMU CSV에서 걸음 수, 케이던스, 걸음 간격 변동성(CV)을 계산하는 스크립트

걸음 검출 방법은 step_core.py 참고 (v1: 처음 버전, v2: 개선 버전)

사용법:
    python tools/step_detect.py data/walk01.csv --truth 45
    python tools/step_detect.py data/walk01.csv --truth 45 --algo v1    # 처음 버전으로
    python tools/step_detect.py data/walk01.csv --truth 45 --sweep      # 임계값별 비교표
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from step_core import (VERSIONS, count_gyro_swings, cv, detect_steps,
                       drop_outliers, step_intervals)

parser = argparse.ArgumentParser()
parser.add_argument("csv", help="분석할 CSV 파일 (imu_logger.py 결과)")
parser.add_argument("--algo", choices=["v1", "v2"], default="v2", help="걸음 검출 버전")
parser.add_argument("--threshold", type=float, default=None, help="걸음 봉우리 최소 크기 (g)")
parser.add_argument("--gyro-height", type=float, default=50.0, help="팔 흔들기 최소 크기 (dps)")
parser.add_argument("--truth", type=int, default=None, help="실제 걸음 수 (오차 계산용)")
parser.add_argument("--sweep", action="store_true", help="여러 임계값으로 비교표 출력")
args = parser.parse_args()

p = dict(VERSIONS[args.algo])
if args.threshold is not None:
    p["threshold"] = args.threshold


def error_text(n, truth):
    if truth is None:
        return ""
    diff = n - truth
    return f"  (정답 {truth}, 오차 {diff:+d}, {diff / truth * 100:+.1f}%)"


# ===== 데이터 읽기 =====
df = pd.read_csv(args.csv)
t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
mag = np.sqrt(df["ax"] ** 2 + df["ay"] ** 2 + df["az"] ** 2).to_numpy()
gz = df["gz"].to_numpy()
fs = 1000.0 / df["t_ms"].diff().mean()

print(f"파일: {args.csv}")
print(f"샘플 {len(df)}개, 길이 {t[-1]:.1f}초, 샘플링 {fs:.1f}Hz")

# ===== 임계값 비교표 =====
if args.sweep:
    print("\n임계값   검출 걸음")
    for th in [1.10, 1.15, 1.20, 1.25, 1.30]:
        n = len(detect_steps(t, mag, fs, dict(p, threshold=th))[0])
        print(f" {th:.2f}g     {n:3d}{error_text(n, args.truth)}")

# ===== 걸음 검출 =====
steps, rejected = detect_steps(t, mag, fs, p)
n_steps = len(steps)
print(f"\n[가속도 {args.algo}] 임계값 {p['threshold']}g, 연속 {p['confirm_n']}걸음 확인"
      + (", 최소 간격 속도 맞춤 " if args.algo == "v2" else ", 최소 간격 0.3초 고정"))
print(f"  걸음 수: {n_steps}{error_text(n_steps, args.truth)}")
if rejected:
    print(f"  제외된 후보 {len(rejected)}개: " + ", ".join(f"{t[i]:.1f}초" for i in rejected))

iv_t, intervals = step_intervals(t, steps, p["max_interval"])
med = np.median(intervals) if len(intervals) >= 3 else None
if med is not None:
    print(f"  걸음 간격 중앙값: {med:.3f}초 → 케이던스 약 {60 / med:.0f}spm")

    # ===== 걸음 간격 변동성 (리듬이 얼마나 일정한가) =====
    normal = drop_outliers(intervals)
    print(f"\n[걸음 간격 변동성]")
    print(f"  평균 {intervals.mean():.3f}초 ± 표준편차 {intervals.std(ddof=1):.3f}초")
    print(f"  변동계수(CV) {cv(intervals):.1f}%  (작을수록 일정한 리듬)")
    print(f"  튀는 간격 {len(intervals) - len(normal)}개 제외 → CV {cv(normal):.1f}%")

# ===== 자이로로 검산 =====
gz_s, swings = count_gyro_swings(t, gz, fs, args.gyro_height)
n_gyro = len(swings) * 2
print(f"\n[자이로 검산] gz 파도 {len(swings)}번 × 2 = {n_gyro}걸음{error_text(n_gyro, args.truth)}")

# ===== 그래프 =====
fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True,
                         gridspec_kw={"height_ratios": [3, 2, 3]})

axes[0].plot(t, mag, color="black", linewidth=0.8, label="|a|")
axes[0].plot(t[steps], mag[steps], "o", color="red", markersize=5, label=f"step ({n_steps})")
if rejected:
    axes[0].plot(t[rejected], mag[rejected], "x", color="gray", markersize=8, mew=2,
                 label=f"rejected ({len(rejected)})")
axes[0].axhline(p["threshold"], color="red", linestyle="--", linewidth=0.8,
                label=f"threshold {p['threshold']}g")
axes[0].axhline(1.0, color="gray", linestyle=":", linewidth=0.8)
axes[0].set_ylabel("|a| (g)")
axes[0].set_title(f"Step detection from acceleration magnitude ({args.algo})")
axes[0].legend(loc="upper right")
axes[0].grid(alpha=0.3)

# ----- 걸음 간격 그래프: 점 하나 = 걸음 사이 시간, 색 = 중앙값에서 벗어난 정도 -----
ax = axes[1]
if med is not None:
    dev = np.abs(intervals - med) / med * 100
    groups = [
        (dev <= 10,                "#2e9e5b", "o", "steady (within 10%)"),
        ((dev > 10) & (dev <= 25), "#e69500", "s", "drifting (10-25%)"),
        (dev > 25,                 "#d03b3b", "X", "off (over 25%)"),
    ]
    ax.axhspan(med * 0.9, med * 1.1, color="#2e9e5b", alpha=0.10)
    ax.axhline(med, color="gray", linestyle="--", linewidth=0.8, label=f"median {med:.2f}s")
    ax.plot(iv_t, intervals, color="lightgray", linewidth=1.0, zorder=1)
    for mask, color, marker, label in groups:
        if mask.any():
            ax.plot(iv_t[mask], intervals[mask], marker, color=color, markersize=7,
                    linestyle="none", zorder=2, label=f"{label}: {mask.sum()}")
    ax.legend(loc="upper left", fontsize=9)
ax.set_ylabel("step interval (s)")
ax.set_title("Step rhythm: time between steps")
ax.grid(alpha=0.3)

axes[2].plot(t, gz, color="lightgray", linewidth=0.8, label="gz raw")
axes[2].plot(t, gz_s, color="green", linewidth=1.0, label="gz smoothed")
axes[2].plot(t[swings], gz_s[swings], "o", color="blue", markersize=5,
             label=f"arm swing ({len(swings)} x 2 = {n_gyro})")
axes[2].axhline(args.gyro_height, color="blue", linestyle="--", linewidth=0.8)
axes[2].set_ylabel("gz (dps)")
axes[2].set_xlabel("time (s)")
axes[2].set_title("Arm swing from gyroscope (cross-check)")
axes[2].legend(loc="upper right")
axes[2].grid(alpha=0.3)

plt.tight_layout()
out_png = args.csv.rsplit(".", 1)[0] + f"_steps_{args.algo}.png"
plt.savefig(out_png, dpi=120)
print(f"\n그래프 저장: {out_png}")
plt.show()