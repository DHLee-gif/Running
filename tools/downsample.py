"""
고속으로 측정한 IMU CSV를 솎아내서 낮은 샘플링 속도 데이터로 만드는 스크립트

같은 걸음 데이터를 샘플링 속도만 바꿔 비교하기 위해 사용한다.
(측정 순서, 피로, 걷는 방식 차이가 섞이지 않음)

예) 208Hz → 104Hz: 2개 중 1개만 남김
    208Hz → 52Hz : 4개 중 1개만 남김

사용법:
    python tools/downsample.py data/odr208_1.csv data/odr208_2.csv --to 104 52 26
    → data/odr208_1_to104.csv ... 를 만들고, 분석용 data/trial_ds.csv 를 만든다.
    python tools/step_report.py --trials data/trial_ds.csv --group odr
"""
import argparse
import os

import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("files", nargs="+", help="원본 CSV (고속 측정)")
parser.add_argument("--src", type=int, default=208, help="원본 샘플링 속도 (Hz)")
parser.add_argument("--to", type=int, nargs="+", default=[104, 52, 26], help="만들 속도들")
parser.add_argument("--trials", default="data/trial_odr.csv", help="정답(truth)을 가져올 기록 파일")
parser.add_argument("--out", default="data/trial_ds.csv", help="만들 분석용 기록 파일")
args = parser.parse_args()

trials = pd.read_csv(args.trials, skipinitialspace=True, encoding="utf-8-sig")
trials["file"] = trials["file"].astype(str).str.strip()
truth_of = dict(zip(trials["file"], trials["truth"]))
bpm_of = dict(zip(trials["file"], trials["bpm"]))

rows = []
for path in args.files:
    name = os.path.basename(path)
    df = pd.read_csv(path)
    base = name.rsplit(".", 1)[0]
    truth, bpm = truth_of.get(name), bpm_of.get(name, 0)

    rows.append({"file": name, "bpm": bpm, "odr": args.src, "truth": truth, "note": "원본"})
    for rate in args.to:
        step = round(args.src / rate)               # 몇 개마다 하나씩 남길지
        out_name = f"{base}_to{rate}.csv"
        df.iloc[::step].to_csv(os.path.join(os.path.dirname(path), out_name), index=False)
        rows.append({"file": out_name, "bpm": bpm, "odr": rate, "truth": truth,
                     "note": f"{name}에서 {step}개마다 1개"})
        print(f"{name} → {out_name}  ({len(df)}행 → {len(df.iloc[::step])}행)")

pd.DataFrame(rows).to_csv(args.out, index=False, encoding="utf-8-sig")
print(f"\n분석용 기록 저장: {args.out}")
print(f"다음: python tools/step_report.py --trials {args.out} --group odr")