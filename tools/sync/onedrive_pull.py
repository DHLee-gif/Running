"""
OneDrive → data/ 복사 (폰에서 'OneDrive로 공유'한 RunBand CSV)

폰: 웹에서 멈춤 → 'OneDrive로 공유' → OneDrive 앱 → RunBand 폴더에 업로드
PC: OneDrive가 C:\\Users\\<나>\\OneDrive\\RunBand 로 동기화 → 이 스크립트가 data/로 복사
    (OneDrive 원본은 그대로 둠 = 클라우드 백업)

사용법:
    python tools/sync/onedrive_pull.py            # 한 번 확인하고 끝
    python tools/sync/onedrive_pull.py --watch    # 켜 두면 10초마다 확인
"""
import argparse
import shutil
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

parser = argparse.ArgumentParser()
parser.add_argument("--src", type=Path, default=Path.home() / "OneDrive" / "RunBand")
parser.add_argument("--dst", type=Path, default=REPO / "data")
parser.add_argument("--watch", action="store_true", help="계속 켜 두고 새 파일 감시")
parser.add_argument("--every", type=float, default=10, help="감시 간격 (초)")
args = parser.parse_args()


def is_stable(p: Path) -> bool:
    """크기가 1초 동안 그대로면 동기화가 끝난 것으로 봄."""
    size = p.stat().st_size
    time.sleep(1)
    return size > 0 and size == p.stat().st_size


def pull() -> int:
    copied = 0
    for p in sorted(args.src.glob("runband_*.csv")):
        out = args.dst / p.name
        if out.exists() and out.stat().st_size == p.stat().st_size:
            continue                                  # 이미 복사함
        if not is_stable(p):
            print(f"  동기화 중, 다음에 다시: {p.name}")
            continue
        action = "덮어씀" if out.exists() else "복사"
        shutil.copy2(p, out)
        print(f"  {action}: {p.name} ({p.stat().st_size / 1024:.0f} KB)")
        copied += 1
    return copied


args.src.mkdir(parents=True, exist_ok=True)           # 처음 실행이면 OneDrive에 RunBand 폴더 생성
args.dst.mkdir(parents=True, exist_ok=True)
print(f"{args.src} → {args.dst}")

if args.watch:
    print(f"{args.every:.0f}초마다 확인 중 (Ctrl+C로 종료)")
    try:
        while True:
            pull()
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("종료")
else:
    n = pull()
    print(f"새 파일 {n}개" if n else "새 파일 없음")
