# 미니 PC 배포 안내

이 툴은 단일 프로세스 웹 서버 하나로 뜹니다. 필요한 것은 Python 3.11 이상, uv, git 세 가지뿐입니다.
DB(`data.db`)와 원본·산출물(`storage/`)은 프로젝트 폴더 안에 파일로 쌓이므로, 그 폴더만 백업하면 됩니다.

---

## 1. 공통 준비

| 항목 | 내용 |
|---|---|
| 필요 소프트웨어 | Python 3.11+, uv, git |
| 네트워크 | 미니 PC → 인터넷(Gemini API) 아웃바운드. 사내에서 접속하려면 8765 포트 인바운드 허용 |
| 디스크 | 카드 1장당 약 2MB(원본 + 슬라이스 + HTML). 1,000장이면 2GB |
| 시간대 | DB 시각은 KST 로 기록하므로 PC 시간대와 무관 |

---

## 2. Ubuntu / Debian 계열 (현재 미니 PC 구성)

경로는 `~/dev/Detailcard`, 서비스는 **사용자 범위(systemd --user)** 로 등록되어 있다. `sudo` 없이 `systemctl --user` 를 쓴다.

### 2-1. 설치

```bash
sudo apt update && sudo apt install -y git python3.11 python3.11-venv curl
curl -LsSf https://astral.sh/uv/install.sh | sh        # uv 설치
source ~/.bashrc

git clone https://github.com/parkilsoon/detailcard-tool.git ~/dev/Detailcard
cd ~/dev/Detailcard
uv sync                                                 # 의존성 설치 (.venv 생성)
cp .env.example .env
nano .env                                               # 아래 4 참고
```

### 2-2. 동작 확인

```bash
uv run pytest -q                                        # 테스트 (LLM 호출 없음)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8765  # 수동 실행
```
다른 PC 브라우저에서 `http://<미니PC IP>:8765` 접속이 되면 Ctrl+C 로 끄고 서비스 등록으로 넘어간다.
방화벽(ufw 사용 시): `sudo ufw allow 8765/tcp`

### 2-3. 서비스 등록 (사용자 범위)

```bash
mkdir -p ~/.config/systemd/user
tee ~/.config/systemd/user/detailcard.service > /dev/null <<'UNIT'
[Unit]
Description=Detail card mobile converter
After=network-online.target

[Service]
WorkingDirectory=%h/dev/Detailcard
ExecStart=%h/dev/Detailcard/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now detailcard
systemctl --user status detailcard --no-pager
sudo loginctl enable-linger $USER     # 로그아웃·재부팅 후에도 서비스가 살아 있게 (한 번만)
```

로그 보기: `journalctl --user -u detailcard -f`
linger 확인: `loginctl show-user $USER | grep Linger` → `Linger=yes` 여야 한다.

> 처리 도중 재시작되면 "추출 중"이던 카드는 자동으로 다시 큐에 들어간다. `--reload` 옵션은 개발용이므로 서비스에는 넣지 않는다.

### 2-4. 업데이트 (코드 반영)

```bash
cd ~/dev/Detailcard && git pull && uv sync && systemctl --user restart detailcard
```

급여 판정처럼 **저장된 데이터의 요약 컬럼 규칙이 바뀐 경우**에는 재시작 전에 한 줄 더:
```bash
systemctl --user stop detailcard
uv run python scripts/resync_columns.py
systemctl --user start detailcard
```

### 2-5. 초기화 (처음부터 다시)

```bash
systemctl --user stop detailcard
cd ~/dev/Detailcard
tar czf ~/detailcard-before-reset-$(date +%F).tgz data.db storage 2>/dev/null   # 백업 (선택)
rm -f data.db data.db-journal && rm -rf storage
systemctl --user start detailcard      # 빈 DB 자동 생성
```

### 2-6. 백업

```bash
tar czf ~/detailcard-backup-$(date +%F).tgz -C ~/dev/Detailcard data.db storage .env
```
매일 자동: `crontab -e` 에 `0 3 * * * tar czf /backup/detailcard-$(date +\%F).tgz -C $HOME/dev/Detailcard data.db storage .env`

---

## 3. Windows 10 / 11

### 3-1. 설치

1. Python 3.11+ 설치 (python.org, "Add to PATH" 체크) 와 Git for Windows 설치
2. PowerShell(관리자 아님) 에서:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # uv 설치 후 PowerShell 재시작
git clone https://github.com/parkilsoon/detailcard-tool.git C:\detailcard
cd C:\detailcard
uv sync
copy .env.example .env
notepad .env                                            # 아래 3-1 참고
```

### 3-2. 동작 확인

```powershell
uv run pytest -q
uv run uvicorn app.main:app --host 0.0.0.0 --port 8765
```
Windows 방화벽이 물어보면 "개인 네트워크 허용". 묻지 않으면 관리자 PowerShell 에서:
```powershell
New-NetFirewallRule -DisplayName "detailcard 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
```

### 3-3. 자동 시작 (작업 스케줄러)

1. `C:\detailcard\run.bat` 파일을 만들고 아래 내용을 넣습니다.
```bat
@echo off
cd /d C:\detailcard
.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8765 >> logs.txt 2>&1
```
2. 작업 스케줄러 → 기본 작업 만들기 → 트리거 "컴퓨터 시작 시" → 동작 "프로그램 시작" → `C:\detailcard\run.bat`
3. 만든 작업의 속성에서 "사용자가 로그온했는지 여부에 관계없이 실행", "가장 높은 수준의 권한으로 실행" 체크, 설정 탭에서 "작업이 실패하면 다시 시작" 체크.

### 3-4. 업데이트 / 백업

```powershell
cd C:\detailcard; git pull; uv sync      # 이후 작업 스케줄러에서 작업 종료 후 다시 실행
Compress-Archive -Path data.db, storage, .env -DestinationPath "$HOME\detailcard-backup-$(Get-Date -Format yyyy-MM-dd).zip"
```

---

## 4. `.env` 설정 (양쪽 공통)

`.env.example` 을 복사한 뒤 아래만 채웁니다. 나머지는 비워 두면 기본값이 적용됩니다.

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<키>
LLM_MAX_TOKENS=16000
PIPELINE_WORKERS=3
```

- `LLM_MAX_TOKENS` 는 반드시 16000 이상. 8000 이면 밀도 높은 카드가 잘립니다.
- 다중 등록에서 API 속도 제한 오류가 잦으면 `PIPELINE_WORKERS=2` 로 낮춥니다.
- Claude 로 바꾸려면 `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=<키>`.

---

## 5. 점검 목록

- [ ] 브라우저에서 목록 화면이 뜬다
- [ ] "새로 등록"으로 PNG 1장을 올려 검수 화면까지 도달한다 (1~2분)
- [ ] "저장" 후 목록에 "등록됨"으로 보이고 HTML 다운로드가 된다
- [ ] "데이터 출력 (CSV)"가 엑셀에서 한글 깨짐 없이 열린다
- [ ] 미니 PC 를 재부팅해도 서비스가 자동으로 떠 있다

문제가 생기면 로그(`journalctl -u detailcard` 또는 `logs.txt`)와 목록의 "실패" 탭 → 카드 → "기술 정보"를 함께 확인합니다.
