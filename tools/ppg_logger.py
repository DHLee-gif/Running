"""
MAX30102 시리얼 데이터를 CSV로 저장하는 로거 (tests/ppg_raw 펌웨어용)

보드 출력 형식: t_ms,red,ir
사용법: python tools/ppg_logger.py --port COM7 --sec 30 --out data/ppg_rest01.csv
※ 실행 전에 시리얼 모니터를 반드시 닫을 것 (포트 충돌)
"""
import argparse
import csv
import time

import serial

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="COM7")
parser.add_argument("--baud", type=int, default=115200)
parser.add_argument("--sec", type=float, default=30, help="기록 시간(초)")
parser.add_argument("--out", default="data/ppg_log.csv")
args = parser.parse_args()

HEADER = ["t_ms", "red", "ir"]

with serial.Serial(args.port, args.baud, timeout=1) as ser, \
        open(args.out, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(HEADER)
    print(f"[{args.port}] 연결됨. 손가락을 센서에 살짝 올리고 움직이지 마세요.")

    start, rows, last_report = None, 0, time.time()
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        parts = line.split(",")
        if len(parts) != 3:                     # 숫자 3개짜리 줄만 저장
            print("  [board]", line)
            continue
        try:
            red, ir = int(parts[1]), int(parts[2])
        except ValueError:
            print("  [board]", line)
            continue

        if start is None:
            start = time.time()
            print("기록 시작!")

        writer.writerow(parts)
        rows += 1

        now = time.time()
        if now - last_report >= 1.0:
            hint = "  ← 손가락이 떨어진 것 같음" if ir < 10000 else ""
            print(f"  {now - start:5.1f}s  {rows}행  ir={ir}{hint}")
            last_report = now
        if now - start >= args.sec:
            break

print(f"완료: {rows}행 → {args.out}")