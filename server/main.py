"""
RunBand 수신 서버 (5-1): 폰 웹에서 보낸 CSV를 data/에 저장

실행:   uvicorn server.main:app --port 8000
외부:   tailscale funnel 8000  →  https://runband-pc.tail0c1c6a.ts.net

GET  /health   연결 확인 (토큰 필요 없음)
GET  /check    토큰 확인 (헤더 X-RunBand-Token)
POST /upload   헤더 X-RunBand-Token + 폼(name, data, temp) → data/<name>.csv, data/<name>_temp.csv
               같은 내용이 이미 있으면 다시 저장하지 않음 (재전송 대비), 내용이 다르면 _2, _3 ...
"""
import hashlib
import re
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
TOKEN_FILE = Path(__file__).with_name("token.txt")
MAX_BYTES = 50 * 1024 * 1024
NAME_RE = re.compile(r"^runband_\d{8}_\d{4}$")          # 웹이 만드는 이름 규칙
HEADERS = {"data": "t_ms,red,ir,ax,ay,az,gx,gy,gz", "temp": "t_ms,temp"}


def load_token() -> str:
    """처음 실행이면 무작위 토큰을 만들어 token.txt에 저장 (gitignore 대상)"""
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


TOKEN = load_token()
print(f"[RunBand] 토큰: {TOKEN}   (폰 웹 설정에 입력)")
print(f"[RunBand] 저장 위치: {DATA}")

app = FastAPI(title="RunBand")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dhlee-gif.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["X-RunBand-Token"],
)


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat(timespec="seconds")}


@app.get("/check")
def check(x_runband_token: str = Header("")):
    """웹 설정의 '연결 확인': 주소와 토큰이 둘 다 맞는지"""
    if not secrets.compare_digest(x_runband_token, TOKEN):
        raise HTTPException(401, "토큰이 맞지 않음")
    return {"ok": True}


async def read_limited(f: UploadFile) -> bytes:
    """최대 크기를 넘으면 중단"""
    chunks, total = [], 0
    while chunk := await f.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(413, "파일이 너무 큼 (50MB 초과)")
        chunks.append(chunk)
    return b"".join(chunks)


def check_csv(body: bytes, kind: str):
    first = body.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    if first != HEADERS[kind]:
        raise HTTPException(400, f"{kind} CSV 첫 줄이 다름: {first[:60]}")


def pick_base(name: str, bodies: dict) -> tuple[str, bool]:
    """저장할 이름 결정. 같은 내용이 이미 있으면 (이름, True)"""
    digest = {k: hashlib.sha256(v).hexdigest() for k, v in bodies.items()}
    for n in range(1, 100):
        base = name if n == 1 else f"{name}_{n}"
        paths = {k: DATA / (base + ("_temp" if k == "temp" else "") + ".csv") for k in bodies}
        if not any(p.exists() for p in paths.values()):
            return base, False
        same = all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == digest[k]
                   for k, p in paths.items())
        if same:
            return base, True
    raise HTTPException(409, "같은 이름이 너무 많음")


@app.post("/upload")
async def upload(name: str = Form(...),
                 data: UploadFile = File(...),
                 temp: UploadFile | None = File(None),
                 x_runband_token: str = Header("")):
    if not secrets.compare_digest(x_runband_token, TOKEN):
        raise HTTPException(401, "토큰이 맞지 않음")
    if not NAME_RE.match(name):
        raise HTTPException(400, "이름 규칙이 다름 (runband_YYYYMMDD_HHMM)")

    bodies = {"data": await read_limited(data)}
    if temp is not None:
        bodies["temp"] = await read_limited(temp)
    for kind, body in bodies.items():
        check_csv(body, kind)

    base, exists = pick_base(name, bodies)
    saved = []
    for kind, body in bodies.items():
        p = DATA / (base + ("_temp" if kind == "temp" else "") + ".csv")
        if not exists:
            DATA.mkdir(exist_ok=True)
            p.write_bytes(body)
        saved.append(p.name)
    rows = bodies["data"].count(b"\n") - 1
    print(f"[RunBand] {'이미 있음' if exists else '저장'}: {', '.join(saved)} ({rows}줄)")
    return {"status": "exists" if exists else "saved", "files": saved, "rows": rows}
