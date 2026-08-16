# my_stock

거래 원장(ledger) 기반 주식 포트폴리오 관리. 웹 UI + CLI.

## 설계 원칙

**진실의 원천은 `transactions` 테이블 하나뿐이다.**
보유수량·평균단가·실현손익·일별 자산추이는 전부 거래에서 파생 계산한다.
`price_daily` / `fx_daily` / `valuation_daily` 는 언제 지워도 되는 캐시다.

이 구조 덕분에 **과거 거래를 나중에 입력해도 자산추이 그래프가 그 시점까지 소급해서 그려진다.**
스냅샷만 쌓는 방식이었다면 앱을 만든 날부터의 그래프밖에 볼 수 없다.

- **원가 계산법**: 이동평균법
- **환율**: 거래일 환율을 `transactions.fx_rate` 에 고정 저장 → 과거 원화 원가가 재현되고,
  현재 환율과의 차이가 자동으로 환차손익으로 분리된다

  ```
  환차손익 = cost_local × (현재환율 − 평균매입환율)
  ```

  덕분에 "종목을 잘 골라서 번 돈"과 "환율이 올라서 번 돈"이 구분된다.

## 구조

```
app/
├── core/           UI 무관 도메인 계층 (CLI·웹·스케줄러 공용)
│   ├── quotes.py       FDR 호출 + 시세/환율 캐시 — 유일한 외부 네트워크 지점
│   ├── ledger.py       거래 → 보유수량/평균단가/실현손익
│   ├── valuation.py    포지션 + 시세 → 평가액/수익률/일별 추이
│   ├── transactions.py 원장 CRUD (저장 후 전체 재검증)
│   ├── targets.py      목표가/손절가 판정
│   └── bootstrap.py    초기 계정 + 기존 하드코딩 데이터 이관
├── api/            FastAPI — 계산하지 않고 core 결과를 직렬화만 한다
├── web/            Jinja2 + 서버 렌더 SVG 차트 (외부 JS 라이브러리 없음)
└── cli/            터미널 명령
myStock.py          기존 진입점 (CLI 래퍼로 유지)
```

## 설치

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env      # SECRET_KEY 를 바꾸세요
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m app.cli init --email you@example.com
```

`init` 은 계정을 만들고, 기존 `myStock.py` 에 하드코딩돼 있던 6종목을
**2024-01-02 기초잔고 매수 거래**로 등록한다 (원본에 매수일자가 없었기 때문).
실제 매수일을 알게 되면 웹 UI 에서 거래를 수정하면 원가와 자산추이가 자동 재계산된다.

## 실행

**웹**

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 0.0.0.0 --port 8001
```

- 화면: http://localhost:8001
- API 문서: http://localhost:8001/docs
- 폰·태블릿: `http://<PC의 LAN IP>:8001` (`--host 0.0.0.0` 이라 같은 공유기에서 접속됨)

> 반드시 `.\.venv\Scripts\python.exe` 로 실행할 것. 그냥 `python` 은 시스템 Python 을 잡아
> `No module named uvicorn` 이 난다. `.\.venv\Scripts\Activate.ps1` 로 venv 를 활성화해두면
> 그 세션에서는 `python` / `uvicorn` / `pytest` / `alembic` 이 모두 venv 것으로 잡힌다.

> 포트는 8000 이 아니라 **8001** 을 쓴다. 이 PC 에서는 다른 프로젝트(`serve.py`,
> `serve-lan.py`)가 8000 을 상시 점유하고 있어 충돌한다.
> 점유 프로세스 확인: `Get-NetTCPConnection -LocalPort 8001 -State Listen`

**CLI** (기존 사용법 그대로)

```powershell
python myStock.py                  # 현재 수익 현황
python myStock.py history --days 365
python -m app.cli sync             # 시세·환율 캐시 갱신
python -m app.cli --help
```

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

## 알아둘 것

- **FDR 의 `end` 날짜는 소스마다 다르게 동작한다.** 미국 주식은 배타적이라 요청한 마지막 날
  종가가 빠지고, 국내 주식·환율은 포함된다. `quotes._fetch_close` 가 하루 더 요청한 뒤
  직접 잘라내는 이유다. 이 처리가 없으면 해외 종목 현재가가 항상 하루씩 밀린다.
- 스케줄러는 매일 18시(KST)에 시세를 수집하고 목표가를 판정한다.
  PC 가 꺼져 며칠 건너뛰어도 다음 실행 때 빈 구간이 자동으로 메워진다.
- 액면분할은 단가 칸에 비율을 넣는다 (2 = 1주 → 2주).

## AWS 배포 시 바꿀 것

1. `.env` 의 `SECRET_KEY` 를 난수로 교체
2. `DATABASE_URL` 을 Postgres 로 (`postgresql+psycopg://...`) — `psycopg[binary]` 추가 설치
3. `app/api/main.py` 의 `SessionMiddleware(https_only=True)` 로 변경
4. `alembic upgrade head` 실행

## 미구현 (다음 단계 후보)

- 예수금·입출금 추적 → 실질수익률(TWR/MWR)
- 증권사 거래내역 CSV 임포트
- 알림 발송 (현재는 화면 배너까지만)
