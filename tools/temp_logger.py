"""
MAX30205 온도 로거 (tests/temp_raw 펌웨어용)

보드 출력: t_ms,temp
사용법: python tools/temp_logger.py --port COM7 --sec 600 --out data/temp_settle01.csv
"""
import argparse
import csv
import time

import serial

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="COM7")
parser.add_argument("--baud", type=int, default=115200)
parser.add_argument("--sec", type=float, default=600, help="기록 시간(초)")
parser.add_argument("--out", default="data/temp_log.csv")
args = parser.parse_args()

with serial.Serial(args.port, args.baud, timeout=1) as ser, \
        open(args.out, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["t_ms", "temp"])
    print(f"[{args.port}] 연결됨.")

    start, rows, last_report, last_temp = None, 0, 0.0, None
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        parts = line.split(",")
        if len(parts) != 2:
            if line:
                print("  [board]", line)
            continue
        try:
            temp = float(parts[1])
        except ValueError:
            continue                              # 헤더 줄
        if temp != temp:                          # nan = 센서 응답 없음
            print("  [board] 온도 읽기 실패")
            continue

        if start is None:
            start = time.time()
            print(f"기록 시작! ({time.strftime('%H:%M:%S')})")
        writer.writerow(parts)
        rows += 1

        el = time.time() - start
        if el - last_report >= 10:                # 10초마다 현재 온도와 변화량
            diff = "" if last_temp is None else f"  (10초 전보다 {temp - last_temp:+.3f})"
            print(f"  {el:6.0f}s  {temp:.3f}°C{diff}")
            last_report, last_temp = el, temp
        if el >= args.sec:
            break

print(f"완료: {rows}행 → {args.out}")