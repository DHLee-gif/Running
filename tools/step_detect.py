"""
IMU CSV에서 걸음 수와 케이던스를 계산하는 스크립트 (PC에서 알고리즘 실험용)

걸음 정의:
    세 축 합 |a| = sqrt(ax² + ay² + az²) 에서
    ① 임계값(threshold) 이상인 봉우리 꼭대기이고
    ② 직전 후보와 최소 간격(min-interval) 이상 떨어져 있으면 "걸음 후보"
    ③ 후보가 최대 간격(max-interval) 이내로 연속 N개(confirm-steps) 나와야
       "걷는 중"으로 인정하고, 앞의 후보까지 포함해 걸음으로 센다.
       → 걷기 전후의 혼자 떨어진 움직임은 걸음으로 세지 않음

검산:
    자이로 gz의 팔 흔들기 파도 1번 = 2걸음

걸음 간격 변동성:
    걸음 사이 시간의 평균, 표준편차, 변동계수(CV = 표준편차 / 평균)
    → 걸음 수가 같아도 일정하게 걸었는지, 들쭉날쭉 걸었는지 구분

사용법:
    python tools/step_detect.py data/walk01.csv --truth 45
    python tools/step_detect.py data/walk01.csv --truth 45 --sweep      # 임계값별 비교표
    python tools/step_detect.py data/walk01.csv --threshold 1.2         # 임계값 직접 지정
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ===== 명령줄 옵션 =====
parser = argparse.ArgumentParser()
parser.add_argument("csv", help="분석할 CSV 파일 (imu_logger.py 결과)")
parser.add_argument("--threshold", type=float, default=1.15, help="걸음 봉우리 최소 크기 (g)")
parser.add_argument("--min-interval", type=float, default=0.3, help="걸음 사이 최소 간격 (초)")
parser.add_argument("--max-interval", type=float, default=2.0, help="걸음 사이 최대 간격 (초)")
parser.add_argument("--confirm-steps", type=int, default=4, help="걷기로 인정할 연속 걸음 수")
parser.add_argument("--gyro-height", type=float, default=50.0, help="팔 흔들기 최소 크기 (dps)")
parser.add_argument("--truth", type=int, default=None, help="실제 걸음 수 (오차 계산용)")
parser.add_argument("--sweep", action="store_true", help="여러 임계값으로 비교표 출력")
args = parser.parse_args()


# ===== 1단계: 걸음 후보 찾기 =====
def find_candidates(t, mag, threshold, min_interval):
    """|a| 봉우리 중 ①② 조건을 만족하는 후보의 인덱스 목록.

    보드(C++)로 옮기기 쉽게 샘플을 하나씩 보면서 판단하는 방식.
    """
    cands = []
    last_t = -1e9
    for i in range(1, len(mag) - 1):
        is_peak = mag[i] > mag[i - 1] and mag[i] >= mag[i + 1]  # 봉우리 꼭대기인가
        if not is_peak or mag[i] < threshold:                  # ① 충분히 큰가
            continue
        if t[i] - last_t < min_interval:                       # ② 직전 후보와 너무 가깝나
            if cands and mag[i] > mag[cands[-1]]:              #    더 큰 봉우리면 교체
                cands[-1] = i
                last_t = t[i]
            continue
        cands.append(i)
        last_t = t[i]
    return cands


# ===== 2단계: 연속 걸음 확인 =====
def confirm_steps(t, cands, max_interval, confirm_n):
    """후보 중 ③ 연속 조건을 만족하는 것만 걸음으로 확정.

    상태 2개:
        서 있음 → 후보를 pending에 모아두다가 confirm_n개 쌓이면 '걷는 중'으로 전환
        걷는 중 → 후보를 바로 걸음으로 확정
    후보 사이가 max_interval보다 벌어지면 '서 있음'으로 돌아가고 pending을 비움.
    """
    steps, rejected, pending = [], [], []
    walking = False
    prev_t = None

    for i in cands:
        if prev_t is not None and t[i] - prev_t > max_interval:
            walking = False          # 간격이 너무 벌어짐 → 걷기 끝
            rejected.extend(pending)  # 확정 못 된 후보는 버림
            pending = []
        prev_t = t[i]

        if walking:
            steps.append(i)
        else:
            pending.append(i)
            if len(pending) >= confirm_n:   # 연속 N개 → 걷기 시작으로 인정
                walking = True
                steps.extend(pending)
                pending = []

    rejected.extend(pending)
    return steps, rejected


# ===== 자이로 검산 =====
def moving_average(x, n):
    """간단한 이동평균 필터 (자이로 잡음 제거용)."""
    return np.convolve(x, np.ones(n) / n, mode="same")


def count_gyro_swings(t, gz, fs, height, min_interval=0.6):
    """gz 파도의 꼭대기 수 = 팔 흔들기 횟수."""
    gz_s = moving_average(gz, max(1, int(fs * 0.1)))  # 0.1초 이동평균
    swings = []
    last_t = -1e9
    for i in range(1, len(gz_s) - 1):
        if gz_s[i] > gz_s[i - 1] and gz_s[i] >= gz_s[i + 1] and gz_s[i] >= height:
            if t[i] - last_t >= min_interval:
                swings.append(i)
                last_t = t[i]
            elif swings and gz_s[i] > gz_s[swings[-1]]:  # 가까운데 더 크면 교체
                swings[-1] = i
                last_t = t[i]
    return gz_s, swings


def error_text(n, truth):
    if truth is None:
        return ""
    diff = n - truth
    return f"  (정답 {truth}, 오차 {diff:+d}, {diff / truth * 100:+.1f}%)"


def detect(t, mag, threshold):
    cands = find_candidates(t, mag, threshold, args.min_interval)
    steps, rejected = confirm_steps(t, cands, args.max_interval, args.confirm_steps)
    return steps, rejected


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
        n = len(detect(t, mag, th)[0])
        print(f" {th:.2f}g     {n:3d}{error_text(n, args.truth)}")

# ===== 가속도로 걸음 검출 =====
steps, rejected = detect(t, mag, args.threshold)
n_steps = len(steps)
print(f"\n[가속도] 임계값 {args.threshold}g, 간격 {args.min_interval}~{args.max_interval}초, "
      f"연속 {args.confirm_steps}걸음 확인")
print(f"  걸음 수: {n_steps}{error_text(n_steps, args.truth)}")
if rejected:
    print(f"  제외된 후보 {len(rejected)}개: " + ", ".join(f"{t[i]:.1f}초" for i in rejected))

iv_t, intervals, med = np.array([]), np.array([]), None
if n_steps >= 3:
    step_t = t[steps]
    intervals = np.diff(step_t)
    iv_t = step_t[1:]                                  # 간격이 끝나는 걸음의 시각 (그래프 x축)
    keep = intervals <= args.max_interval              # 걷기 사이 공백 제외
    iv_t, intervals = iv_t[keep], intervals[keep]
    med = np.median(intervals)
    print(f"  걸음 간격 중앙값: {med:.3f}초 → 케이던스 약 {60 / med:.0f}spm")

    # ===== 걸음 간격 변동성 (리듬이 얼마나 일정한가) =====
    mean, sd = intervals.mean(), intervals.std(ddof=1)
    cv = sd / mean * 100
    print(f"\n[걸음 간격 변동성]")
    print(f"  평균 {mean:.3f}초 ± 표준편차 {sd:.3f}초")
    print(f"  변동계수(CV) {cv:.1f}%  (작을수록 일정한 리듬)")

    # 중앙값의 1.5배 초과 = 놓친 걸음 / 0.5배 미만 = 걸음이 아닌 움직임 → 둘 다 제외
    normal = intervals[(intervals >= med * 0.5) & (intervals <= med * 1.5)]
    n_out = len(intervals) - len(normal)
    cv2 = normal.std(ddof=1) / normal.mean() * 100
    print(f"  튀는 간격 {n_out}개 제외 → CV {cv2:.1f}%")
    
    print("  간격 목록:", np.round(intervals, 2))

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
axes[0].axhline(args.threshold, color="red", linestyle="--", linewidth=0.8,
                label=f"threshold {args.threshold}g")
axes[0].axhline(1.0, color="gray", linestyle=":", linewidth=0.8)
axes[0].set_ylabel("|a| (g)")
axes[0].set_title("Step detection from acceleration magnitude")
axes[0].legend(loc="upper right")
axes[0].grid(alpha=0.3)

# ----- 걸음 간격 그래프: 점 하나 = 걸음 사이 시간, 색 = 중앙값에서 벗어난 정도 -----
ax = axes[1]
if med is not None:
    dev = np.abs(intervals - med) / med * 100          # 중앙값에서 몇 % 벗어났나
    groups = [
        (dev <= 10,                "#2e9e5b", "o", "steady (within 10%)"),
        ((dev > 10) & (dev <= 25), "#e69500", "s", "drifting (10-25%)"),
        (dev > 25,                 "#d03b3b", "X", "off (over 25%)"),
    ]
    ax.axhspan(med * 0.9, med * 1.1, color="#2e9e5b", alpha=0.10)   # ±10% 띠
    ax.axhline(med, color="gray", linestyle="--", linewidth=0.8,
               label=f"median {med:.2f}s")
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
out_png = args.csv.rsplit(".", 1)[0] + "_steps.png"
plt.savefig(out_png, dpi=120)
print(f"\n그래프 저장: {out_png}")
plt.show()