"""
걸음 검출 공통 함수 (step_detect.py, evaluate.py가 함께 사용)

v1 (처음 버전)
    ① |a| 봉우리가 임계값 이상
    ② 직전 후보와 최소 간격 0.3초 이상 (고정)
    ③ 연속 N걸음이 나와야 걷기로 인정

v2 (개선 버전) — v1에 한 가지 추가
    A. 최소 간격을 걷는 속도에 맞춤
       최근 걸음 간격 중앙값 × 0.4 (단, 0.3초보다 작아지지 않음)
       → 느리게 걸을 때 한 걸음 안의 두 번째 충격(0.3~0.4초 뒤)을 걸러냄

    (시도했다가 뺀 것) 걸음 시각을 충격의 무게중심으로 잡기 (center_s)
       → 실제 데이터에서 CV가 오히려 늘어서 0으로 끔
"""
import numpy as np

V1 = {"threshold": 1.15, "min_interval": 0.3, "max_interval": 2.0, "confirm_n": 4,
      "adaptive": 0.0, "center_s": 0.0}
V2 = dict(V1, adaptive=0.4, center_s=0.0)
VERSIONS = {"v1": V1, "v2": V2}


def moving_average(x, n):
    """이동평균 필터."""
    return np.convolve(x, np.ones(n) / n, mode="same")


# ===== 1단계: 걸음 후보 찾기 =====
def find_candidates(t, mag, threshold, min_interval, adaptive=0.0, history=5):
    """|a| 봉우리 중 ①② 조건을 만족하는 후보의 인덱스 목록.

    adaptive > 0 이면 최소 간격 = max(min_interval, 최근 간격 중앙값 × adaptive)
    """
    cands, gaps = [], []
    last_t = -1e9
    for i in range(1, len(mag) - 1):
        is_peak = mag[i] > mag[i - 1] and mag[i] >= mag[i + 1]
        if not is_peak or mag[i] < threshold:
            continue

        gap = min_interval
        recent = [g for g in gaps[-history:] if g < 2.0]   # 걷기 사이 공백은 제외
        if adaptive > 0 and len(recent) >= 3:
            gap = max(min_interval, np.median(recent) * adaptive)

        if t[i] - last_t < gap:                 # 직전 후보와 너무 가까움
            if cands and mag[i] > mag[cands[-1]]:  # 더 큰 봉우리면 교체
                if len(cands) >= 2:
                    gaps[-1] = t[i] - t[cands[-2]]
                cands[-1] = i
                last_t = t[i]
            continue

        if cands:
            gaps.append(t[i] - last_t)
        cands.append(i)
        last_t = t[i]
    return cands


# ===== 2단계: 연속 걸음 확인 =====
def confirm_steps(t, cands, max_interval, confirm_n):
    """후보 중 연속 confirm_n개 이상 이어진 것만 걸음으로 확정."""
    steps, rejected, pending = [], [], []
    walking, prev_t = False, None
    for i in cands:
        if prev_t is not None and t[i] - prev_t > max_interval:
            walking = False
            rejected.extend(pending)
            pending = []
        prev_t = t[i]
        if walking:
            steps.append(i)
        else:
            pending.append(i)
            if len(pending) >= confirm_n:
                walking = True
                steps.extend(pending)
                pending = []
    rejected.extend(pending)
    return steps, rejected


# ===== 3단계(v2): 걸음 시각 다시 잡기 =====
def refine_times(mag, idx, fs, window_s):
    """각 걸음 주변 ±window_s 안 충격의 '무게중심' 시각으로 옮김.

    봉우리 하나를 고르면, 비슷한 봉우리 두 개 중 어느 쪽이 크냐에 따라 시각이 튄다.
    1g를 넘는 부분의 크기를 무게로 시각을 평균 내면, 두 봉우리의 가운데로 안정된다.
    """
    if window_s <= 0:
        return list(idx)
    w = int(fs * window_s)
    out = []
    for i in idx:
        lo, hi = max(0, i - w), min(len(mag), i + w + 1)
        weight = np.clip(mag[lo:hi] - 1.0, 0, None) ** 2   # 큰 충격일수록 무게 큼
        if weight.sum() == 0:
            out.append(i)
            continue
        center = np.sum(np.arange(lo, hi) * weight) / weight.sum()
        out.append(int(round(center)))
    return out


def detect_steps(t, mag, fs, p):
    """설정 p(V1 또는 V2)로 걸음 검출. (steps, rejected) 인덱스 목록 반환."""
    cands = find_candidates(t, mag, p["threshold"], p["min_interval"], p["adaptive"])
    steps, rejected = confirm_steps(t, cands, p["max_interval"], p["confirm_n"])
    return refine_times(mag, steps, fs, p["center_s"]), rejected


# ===== 자이로 검산 =====
def count_gyro_swings(t, gz, fs, height=50.0, min_interval=0.6):
    """gz 파도의 꼭대기 수 = 팔 흔들기 횟수."""
    gz_s = moving_average(gz, max(1, int(fs * 0.1)))
    swings, last_t = [], -1e9
    for i in range(1, len(gz_s) - 1):
        if gz_s[i] > gz_s[i - 1] and gz_s[i] >= gz_s[i + 1] and gz_s[i] >= height:
            if t[i] - last_t >= min_interval:
                swings.append(i)
                last_t = t[i]
            elif swings and gz_s[i] > gz_s[swings[-1]]:
                swings[-1] = i
                last_t = t[i]
    return gz_s, swings


# ===== 걸음 간격과 CV =====
def step_intervals(t, steps, max_interval):
    """(간격이 끝나는 시각, 간격) — 걷기 사이 공백은 제외."""
    st = t[steps]
    iv = np.diff(st)
    keep = iv <= max_interval
    return st[1:][keep], iv[keep]


def cv(x):
    return x.std(ddof=1) / x.mean() * 100 if len(x) >= 3 else np.nan


def drop_outliers(x):
    """중앙값의 0.5배 미만(걸음 아닌 움직임) / 1.5배 초과(놓친 걸음) 간격 제외."""
    if len(x) == 0:
        return x
    med = np.median(x)
    return x[(x >= med * 0.5) & (x <= med * 1.5)]