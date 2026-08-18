# 경영 대시보드 서버 PC 배포 — Codex 인수인계

> 작성 기준: 2026-08-18 17:25 KST
> 대상: 씽크와이즈 DB에 접근 가능한 상시 가동 Windows 서버 PC에서 새로 연 Codex 세션
> 최우선 목표: 이번 주 안에 대표이사에게 경영 대시보드를 비공개 HTTPS로 납품하고 실제 기기 인수 시험까지 끝낸다.

## 0. 새 Codex가 받는 실행 지시

이 문서를 끝까지 읽은 뒤 사용자가 기존 대화를 다시 설명하게 하지 말고, 아래 사전 점검부터 순서대로 작업한다. 안전하게 발견할 수 있는 값은 직접 확인하고, 비밀번호·메일 주소·토큰 같은 비밀값만 사용자에게 서버의 `.env`에 직접 입력해 달라고 요청한다. 코드·설정·테스트·문서를 변경하면 반드시 같은 작업 안에서 `경영대시보드_개발진행현황.md`도 갱신한다.

저장소의 `AGENTS.md` 지침이 항상 우선한다. 작업 시작 시 다음 파일을 읽되, 실행 맥락과 순서는 이 인수인계 문서를 기준으로 한다.

1. `AGENTS.md`
2. `경영대시보드_기획서.md`
3. `경영대시보드_개발진행현황.md`
4. `경영대시보드_예시화면_v2.html`
5. `배포_체크리스트.md`

## 1. 목표와 범위

이번 세션의 목표는 새 기능 개발이 아니라 **현재 구현을 서버 PC에 안전하게 배포하고 납품 기준을 검증하는 것**이다.

포함 범위:

- `yjs_backoffice`와 `thinkwise-wiki`를 같은 서버에 배치
- 두 시스템이 하나의 `wiki_index.db`를 공유하도록 설정
- 씽크와이즈 SELECT 전용 실데이터 연결
- 대시보드·위키 증분 동기화의 Windows 부팅 자동시작
- 다우오피스·Gmail·네이버 IMAP 실계정 검증
- Tailscale Serve 비공개 HTTPS와 대표이사 지정 기기 접근 제한
- 재부팅·외부망·권한 거부·상태 보존·백업까지 실제 인수 시험

이번 납품에서 제외할 범위:

- MCP 서버, AI 업무 요약, NAS 통합 데이터 플랫폼
- 위키 검색 기능의 추가 개편
- 공개 인터넷 배포, 포트포워딩, Tailscale Funnel
- 씽크와이즈 DB 스키마 변경이나 데이터 쓰기

대시보드 납품 뒤 공유 색인을 데이터 플랫폼·MCP로 확장할 계획이지만, 이번 주 납품을 지연시키는 구조 확장은 하지 않는다.

## 2. 확정 아키텍처

```text
씽크와이즈 MariaDB
  ├─ work_log ── 위키 증분 동기화가 60초마다 PK 커서 SELECT 1회
  │                    ↓
  │          thinkwise-wiki/data/wiki_index.db
  │                 ├─ 위키 검색
  │                 └─ 대시보드 최근 변경·실제 최종 활동
  │
  └─ 협업방 기본정보·현재 접속자·30일 활동자
          └─ 대시보드가 소량 SELECT

대시보드 127.0.0.1:8080
          ↓ Tailscale Serve 비공개 HTTPS
대표이사 PC·휴대폰
```

중요한 의미:

- `work_log` 대량 데이터는 위키가 한 번만 증분 수집하며, 위키와 대시보드가 같은 SQLite 원본을 각 용도에 맞게 파생 조회한다.
- 대시보드와 위키가 DB를 각각 대량 조회하는 구조가 아니다.
- 서버 PC는 MariaDB가 설치된 PC일 필요는 없지만, MariaDB 주소와 3306 포트에 접근할 수 있어야 한다.
- 대표이사 기기는 DB에 직접 접근하지 않고 Tailscale HTTPS 화면만 연다.

검토한 선택지 중 채택한 것은 “두 저장소를 서버에 함께 배포하고 공유 색인 하나를 사용”하는 방식이다. 대시보드의 독립 대량 조회는 중복 부하 때문에 배제했고, 전체 데이터 플랫폼·MCP 선행 구축은 이번 납품에 과도해 연기했다.

## 3. 현재 구현 상태

개발 PC에서 마지막 확인한 결과:

- Python 전체 테스트: `49 passed`
- Python 의존성: `pip check` 통과
- Python·JavaScript·PowerShell 구문 검사 통과
- PowerShell 배포 스크립트는 Windows PowerShell 5.1 호환 ASCII 메시지 사용
- HTML ID 중복·위험 DOM 출력 없음
- 실데이터 API: 상태 `ok`, 공유 색인 healthy, stale=false
- 당시 데이터: 프로젝트 87건, 개설자 87건, 최근 변경 30건
- 공유 색인 당시 행 수: 539,250건
- 대시보드 프로젝트 SELECT 약 1.1초, 기타 소량 SELECT 약 0.002초 이하

위 숫자는 데이터 증가에 따라 달라지므로 서버 인수 시험에서 정확히 87건을 요구하지 않는다. 프로젝트가 1건 이상이고 상태 합계가 전체와 일치하며 source가 healthy·stale=false인지 검증한다.

Phase 상태:

- Phase 1 백엔드·캐시: 완료
- Phase 3 수동 상태·설정·백업: 완료
- Phase 2 실제 브라우저 화면: 서버 실기기 검증 대기
- Phase 4 메일: 가짜 IMAP 검증 완료, 실제 3계정 대기
- Phase 5 상주화·Tailscale: 스크립트 구현 완료, 서버·실기기 대기

## 4. 가장 먼저 확인할 전달 위험

### 대시보드 최신 코드가 서버에 실제로 있는지 확인

작성 시점 개발 PC의 `yjs_backoffice` 최신 구현은 기준 커밋 `66ebb64` 위에 아직 커밋되지 않은 변경을 포함한다. 따라서 서버에서 단순히 `origin/main`만 clone하면 최신 대시보드 코드와 이 문서가 빠질 수 있다.

반면 `thinkwise-wiki`는 작성 시점 로컬 작업 트리가 깨끗했고 `main` 커밋 `9d25960`에서 `origin/main`을 추적하고 있었다. 이는 마지막으로 알고 있는 원격 상태이며, 서버에서는 다시 확인한다.

서버에서 아래 필수 파일을 먼저 검사한다.

```powershell
$DashboardRoot = (Get-Location).Path
$required = @(
  "app\mail.py",
  "app\state_store.py",
  "app\worklog_index.py",
  "scripts\audit_delivery_readiness.ps1",
  "scripts\configure_tailscale_serve.ps1",
  "scripts\install_startup_tasks.ps1",
  "scripts\run_dashboard.ps1",
  "scripts\run_thinkwise_index_sync.ps1",
  "scripts\secure_runtime_acl.ps1",
  "scripts\verify_delivery.ps1",
  "서버PC_Codex_인수인계.md",
  "배포_체크리스트.md"
)
$missing = $required | Where-Object {
  -not (Test-Path -LiteralPath (Join-Path $DashboardRoot $_) -PathType Leaf)
}
if ($missing) {
  $missing
  throw "최신 대시보드 작업 트리가 서버에 전달되지 않았습니다."
}
```

하나라도 없으면 구현을 다시 만들거나 오래된 코드로 배포하지 않는다. 다음 중 하나로 최신 작업 트리를 먼저 전달한다.

1. 권장: 개발 PC에서 변경을 검토해 커밋·push한 뒤 서버에서 그 브랜치/커밋을 받는다.
2. 긴급 대안: 개발 PC의 현재 작업 트리를 서버에 복사한다. `.env`, `.venv`, `data/*.db`, 로그는 복사하지 않고 서버에서 새로 구성한다.

이 전달 문제를 해결하기 전에는 납품 작업을 진행하지 않는다.

## 5. 절대 위반하지 않을 안전 원칙

- 씽크와이즈 MariaDB에는 **SELECT만** 실행한다. `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, DDL, 프로시저 실행을 금지한다.
- 실제 비밀번호·토큰·메일 주소는 `.env`에만 저장한다. 채팅, 명령 인자, 진행 문서, Git diff, 로그에 출력하지 않는다.
- `.env` 내용을 `Get-Content`, `type`, `cat` 등으로 화면에 출력하지 않는다.
- 대시보드는 `127.0.0.1`에만 바인딩한다. `0.0.0.0`, LAN 직접 공개, 공유기 포트포워딩을 금지한다.
- `tailscale funnel`을 사용하지 않는다. 기존 Funnel이 있으면 즉시 중단하고 사용자에게 알린다.
- Tailscale Serve의 기존 설정이 다른 서비스를 제공 중이면 덮어쓰지 말고 먼저 사용자에게 보고한다.
- 기존 파일이나 설정은 사용자 소유다. 불명확한 변경을 삭제·초기화하지 않는다.
- 실계정·실기기 시험을 통과하지 않았으면 Phase 2·4·5나 전체 납품을 완료로 기록하지 않는다.

## 6. 서버 사전 조건과 필요한 사용자 입력

Codex가 읽기 전용으로 먼저 확인할 항목:

- Windows 서버이며 관리자 PowerShell 사용 가능
- 서버가 상시 가동되고 재부팅 시험 가능
- Python 3.11 이상, Git, Tailscale 설치 가능
- 서버에서 씽크와이즈 DB 호스트·포트에 접근 가능
- 두 저장소를 둘 충분한 디스크 공간
- 8080 로컬 포트를 다른 프로세스가 사용하지 않음
- 기존 Tailscale Serve/Funnel/Grants와 충돌하지 않음

사용자만 제공하거나 직접 입력할 값:

- 씽크와이즈 SELECT 전용 계정
- 대표이사 Tailscale 로그인 식별자
- 대표이사 PC·휴대폰의 Tailscale 기기/IP
- 다우오피스·Gmail·네이버 IMAP 사용자와 앱 비밀번호
- 각 웹메일의 HTTPS 받은편지함 URL

비밀값을 채팅으로 요청하지 않는다. `.env.example`을 `.env`로 복사한 뒤 사용자에게 서버에서 직접 편집하게 한다. Codex는 값 자체가 아니라 키 존재 여부와 자동 감사 결과만 확인한다.

## 7. 권장 폴더와 환경 구성

권장 구조:

```text
C:\YJS\
├── yjs_backoffice\
└── thinkwise-wiki\
```

설치 드라이브나 상위 폴더는 바꿔도 된다. 두 저장소 이름을 유지하면 기본 경로가 자동으로 맞는다. 다른 위치라면 모든 배포 스크립트에 `-WikiRoot`를 명시한다.

관리자 PowerShell에서:

```powershell
$InstallRoot = "C:\YJS"
$DashboardRoot = Join-Path $InstallRoot "yjs_backoffice"
$WikiRoot = Join-Path $InstallRoot "thinkwise-wiki"
$PythonPath = Join-Path $DashboardRoot ".venv\Scripts\python.exe"

Test-Path -LiteralPath $DashboardRoot -PathType Container
Test-Path -LiteralPath $WikiRoot -PathType Container
python --version
```

두 저장소가 준비된 뒤 같은 가상환경에 양쪽 요구사항을 함께 설치한다.

```powershell
Set-Location -LiteralPath $DashboardRoot
python -m venv .venv
$PythonPath = Join-Path $DashboardRoot ".venv\Scripts\python.exe"
& $PythonPath -m pip install `
  -r (Join-Path $DashboardRoot "requirements.txt") `
  -r (Join-Path $WikiRoot "requirements.txt")
& $PythonPath -m pip check
```

의존성 다운로드가 샌드박스·네트워크 정책으로 실패하면 우회하지 말고 필요한 승인만 요청한다.

## 8. `.env` 구성

대시보드:

```powershell
Set-Location -LiteralPath $DashboardRoot
if (-not (Test-Path -LiteralPath .env -PathType Leaf)) {
  Copy-Item .env.example .env
}
```

대시보드 `.env`의 필수 운영 형태는 다음과 같다. 아래 placeholder를 실제 값으로 문서에 기록하지 않는다.

```dotenv
APP_ENV=production
APP_HOST=127.0.0.1
APP_PORT=8080
APP_DEMO_MODE=false
APP_TRUST_TAILSCALE_HEADERS=true
APP_ALLOWED_TAILSCALE_USER=<대표이사 Tailscale 로그인>

DB_HOST=<씽크와이즈 MariaDB 주소>
DB_PORT=3306
DB_USER=<SELECT 전용 계정>
DB_PASSWORD=<비밀값>
DB_CHARSET=utf8
DB_REFRESH_SECONDS=60
WORK_LOG_REFRESH_SECONDS=60

THINKWISE_INDEX_PATH=..\thinkwise-wiki\data\wiki_index.db
THINKWISE_INDEX_MAX_AGE_SECONDS=180
SQLITE_PATH=data/dashboard.db
MAIL_REFRESH_SECONDS=300
```

메일은 세 공급자 각각 `MAIL_*_ENABLED=true`, 호스트, 포트, 사용자, 앱 비밀번호, `https://` URL을 설정한다. 다우오피스 사용자는 아이디만이 아니라 전체 메일 주소여야 한다.

위키에도 `.env.example`을 `.env`로 복사하고 같은 SELECT 전용 DB 접속값을 설정한다. 권장 폴더 구조에서는 `INDEX_DB_PATH`를 설정하지 않아 기본 `data/wiki_index.db`를 사용한다. 별도 경로를 쓰면 대시보드의 `THINKWISE_INDEX_PATH`와 정확히 같은 파일이어야 한다.

설정 후 `.env`가 Git 대상이 아닌지 확인하되 내용은 출력하지 않는다.

```powershell
git -C $DashboardRoot status --short
git -C $WikiRoot status --short
```

## 9. 실행 순서

### 9.1 코드 자동 검증

```powershell
Set-Location -LiteralPath $DashboardRoot
& $PythonPath -m pytest
& $PythonPath -m compileall -q app tests scripts
& $PythonPath -m pip check
```

기준은 최소 49개 테스트 전부 통과다. 서버에 전달된 이후 테스트 수가 늘었다면 늘어난 전체가 통과해야 한다.

### 9.2 SELECT 전용 DB 사전 진단

```powershell
Set-Location -LiteralPath $DashboardRoot
& $PythonPath scripts\validate_phase0.py
```

이 스크립트는 SELECT 진단만 수행한다. 실패하면 호스트·포트·방화벽·읽기 전용 계정·문자셋을 확인한다. DB 권한을 넓히거나 쓰기 쿼리로 시험하지 않는다.

### 9.3 비밀값과 데이터 폴더 ACL 제한

관리자 PowerShell에서:

```powershell
Set-Location -LiteralPath $DashboardRoot
.\scripts\secure_runtime_acl.ps1 -WikiRoot $WikiRoot
```

SYSTEM·관리자·현재 배포 사용자만 `.env`와 두 데이터 폴더에 접근하도록 제한한다. 다른 서비스 계정이 필요한 기존 구성이 발견되면 임의로 제거하지 말고 중단한다.

### 9.4 공유 색인 최초 생성과 증분 확인

최초 1회만 전체 동기화하고, 이어서 증분 동기화를 한 번 확인한다.

```powershell
Push-Location -LiteralPath $WikiRoot
& $PythonPath -m app.sync --full
if ($LASTEXITCODE -ne 0) { throw "Initial wiki index sync failed." }
& $PythonPath -m app.sync
if ($LASTEXITCODE -ne 0) { throw "Incremental wiki index sync failed." }
Pop-Location
```

전체 동기화를 60초마다 반복하지 않는다. 예약 작업은 `python -m app.sync` 증분 모드만 사용한다.

### 9.5 대시보드 전경 실행과 로컬 검증

첫 관리자 PowerShell:

```powershell
Set-Location -LiteralPath $DashboardRoot
.\scripts\run_dashboard.ps1
```

다른 관리자 PowerShell에서 경로 변수를 다시 설정한 뒤:

```powershell
Set-Location -LiteralPath $DashboardRoot
$AllowedTailscaleUser = Read-Host "Allowed Tailscale login"
.\scripts\verify_delivery.ps1 `
  -AllowedTailscaleUser $AllowedTailscaleUser `
  -RequireProduction
Remove-Variable AllowedTailscaleUser
```

로그인 식별자는 `Read-Host`로 세션 변수에만 받아 명령 기록에 직접 남기지 않고 검증 직후 제거한다. 비밀번호는 절대 명령 인자에 넣지 않는다.

성공 기준:

- 포트 8080이 `127.0.0.1` 또는 `::1`에서만 LISTEN
- `/api/health` 상태 `ok`
- demo mode가 아님
- 공유 색인 source healthy, stale=false
- 프로젝트 1건 이상

### 9.6 부팅 자동시작 등록

전경 서버를 종료한 뒤 관리자 PowerShell에서:

```powershell
Set-Location -LiteralPath $DashboardRoot
.\scripts\install_startup_tasks.ps1 -WikiRoot $WikiRoot -StartNow
Get-ScheduledTask -TaskName "YJS*" | Select-Object TaskName, State
```

등록되는 작업:

- `YJS ThinkWise Shared Index Sync`
- `YJS Management Dashboard`

둘 다 SYSTEM, 부팅 시 시작, 실패 시 1분 뒤 재시작, 중복 실행 금지다. 설치 스크립트는 두 앱의 색인 경로가 다르거나 공유 색인이 없으면 작업을 등록하지 않는다.

### 9.7 Tailscale Serve 구성

먼저 Tailscale을 설치하고 로그인한다. 기존 설정을 읽기 전용으로 확인한다.

```powershell
tailscale status
tailscale serve status
tailscale funnel status
```

기존 Serve가 다른 서비스를 제공하거나 Funnel이 인터넷 공개 중이면 중단한다. 충돌이 없고 대시보드가 실행 중일 때:

```powershell
Set-Location -LiteralPath $DashboardRoot
.\scripts\configure_tailscale_serve.ps1 -DeviceName "yj-dashboard"
tailscale serve status
```

장치 이름은 회사명·직원명·업무명이 드러나지 않는 비민감 DNS 이름을 사용한다. 기본값은 `yj-dashboard`다.

Tailscale 관리자 정책은 대표이사 PC·휴대폰만 `tag:management-dashboard`의 TCP 443에 접근하도록 제한한다. 실제 IP나 로그인 값은 저장소에 기록하지 않는다.

```json
{
  "hosts": {
    "ceo-pc": "<대표이사 PC Tailscale IP>",
    "ceo-phone": "<대표이사 휴대폰 Tailscale IP>"
  },
  "tagOwners": {
    "tag:management-dashboard": []
  },
  "grants": [
    {
      "src": ["ceo-pc", "ceo-phone"],
      "dst": ["tag:management-dashboard"],
      "ip": ["tcp:443"]
    }
  ]
}
```

기존의 광범위한 `src: ["*"]` 또는 `autogroup:member` 규칙이 같은 서버·포트를 허용하면 위 규칙을 추가하는 것만으로는 전용 접근이 되지 않는다. 정책 검사에서 허용 두 기기와 거부 기기를 모두 시험한다.

### 9.8 재부팅과 최종 자동 감사

서버 재부팅 승인을 사용자에게 확인한 뒤 재부팅한다. 부팅 후 3분 이내에 두 작업이 Running인지 확인하고:

```powershell
$InstallRoot = "C:\YJS"
$DashboardRoot = Join-Path $InstallRoot "yjs_backoffice"
$WikiRoot = Join-Path $InstallRoot "thinkwise-wiki"

Set-Location -LiteralPath $DashboardRoot
.\scripts\audit_delivery_readiness.ps1 -WikiRoot $WikiRoot -DeviceName "yj-dashboard"
```

자동 감사의 모든 항목이 PASS여야 한다. 감사는 다음을 검사한다.

- 두 앱을 import할 수 있는 공유 Python 환경
- 운영·실데이터·Tailscale 사용자 설정
- 위키와 대시보드가 같은 색인 파일 사용
- localhost 단독 LISTEN과 보안 헤더
- 신선한 실데이터·메일 스냅샷
- 오늘자 SQLite 백업 조회 가능
- 두 예약 작업 Running/SYSTEM
- `.env`·SQLite ACL
- Tailscale 연결·비민감 이름·Serve localhost 프록시
- 공개 Funnel 없음

하나라도 FAIL이면 원인을 해결하고 다시 실행한다. 실패를 문서에서 숨기거나 완료로 바꾸지 않는다.

## 10. 실제 기기 인수 시험

자동 감사 뒤 아래 수동 시험을 모두 수행한다.

1. 대표이사 PC에서 Tailscale HTTPS 주소 접속
2. 대표이사 휴대폰에서 Wi-Fi를 끄고 외부 이동통신망으로 접속
3. 허용되지 않은 다른 Tailscale 계정 또는 미등록 기기에서 접속 거부 확인
4. 프로젝트·최근 활동·현재 접속자·차트가 실제 데이터로 표시되는지 확인
5. 검색과 현재/전체/상태 필터, 오래 멈춤 펼치기 확인
6. 프로젝트 수동 상태 변경 후 새로고침해 유지 확인
7. 서버 재부팅 후에도 수동 상태와 설정 유지 확인
8. 다우오피스·Gmail·네이버 안 읽은 수와 최근 헤더를 각 웹메일과 대조
9. 대시보드 조회 뒤 메일이 읽음 처리되지 않았는지 확인
10. `data/backups/dashboard-YYYY-MM-DD.db`에서 `project_mark`, `setting` 조회 가능 확인

실제 화면에서 제목·메일 내용·직원 이름이 보이는 캡처는 저장소나 공개 기록에 남기지 않는다.

## 11. 중단 조건과 복구 원칙

다음 상황에서는 추측으로 진행하지 말고 중단해 사용자에게 구체적으로 보고한다.

- 서버에 최신 대시보드 필수 파일이 없음
- DB 접속에 SELECT보다 넓은 권한이 필요하다고 보임
- 공유 색인 스키마 계약 불일치 또는 위키·대시보드가 다른 파일을 가리킴
- 8080이 비루프백 주소로 LISTEN 중
- 기존 Tailscale Serve/Funnel/Grants와 충돌
- 서버의 기존 ACL·서비스 계정을 제거해야만 진행 가능
- 실제 메일 자격증명 또는 대표이사 기기 승인이 없음
- 자동 감사나 실제 기기 시험이 실패함

되돌리기 쉬운 순서로 작업한다.

- 예약 작업 등록 전 전경 실행으로 먼저 검증
- Serve 변경 전 기존 상태 기록
- 재부팅 전 자동시작 작업 상태 확인
- 문제가 생기면 작업을 삭제하기보다 먼저 `Stop-ScheduledTask` 또는 `Disable-ScheduledTask`로 비활성화하고 원인을 조사
- `.env`·DB·공유 색인을 삭제하거나 초기화하지 않음

## 12. 완료 기준과 최종 보고

다음이 모두 충족되어야 납품 완료다.

- 전체 테스트 통과
- SELECT 전용 DB 진단 통과
- 초기 전체 색인과 증분 동기화 통과
- 서버 재부팅 후 두 예약 작업 자동 복구
- 최종 자동 감사 전 항목 PASS
- 대표이사 PC·외부망 휴대폰 접속 성공
- 비허용 계정·기기 접속 거부
- 3개 메일 실계정 수치·읽음 보존 확인
- 상태·설정 재부팅 후 유지
- 일일 백업 복원 조회 확인
- `경영대시보드_개발진행현황.md`에 KST 시각·검증 결과·남은 실패를 정확히 기록

최종 보고에는 비밀값 없이 다음만 포함한다.

- 배포 서버에서 실행된 구성 요약
- 테스트·자동 감사·재부팅·실기기 시험 결과
- 대표이사가 사용할 Tailscale HTTPS 주소는 필요 시 사용자에게만 전달하고 저장소에는 기록하지 않음
- 남은 제한이나 운영자가 해야 할 일
- 변경 파일과 커밋 여부

## 13. 첫 실행 체크리스트

새 Codex는 다음 순서로 바로 시작한다.

- [ ] 필수 문서 5개 읽기
- [ ] 최신 대시보드 작업 트리 전달 여부 확인
- [ ] `git status`로 두 저장소 상태 확인
- [ ] 서버 OS·관리자 권한·Python·Tailscale·8080·DB 네트워크 사전 점검
- [ ] 비밀값을 출력하지 않는 `.env` 구성 안내
- [ ] 두 저장소 요구사항을 공유 가상환경에 설치
- [ ] 전체 테스트와 SELECT 진단
- [ ] ACL → 전체 색인 → 증분 색인
- [ ] 전경 대시보드와 localhost 검증
- [ ] 자동시작 등록 → Tailscale Serve/Grants
- [ ] 사용자 승인 후 재부팅
- [ ] 자동 감사 전 항목 PASS
- [ ] 대표이사 PC·외부망 휴대폰·거부 기기·실메일 인수 시험
- [ ] 진행 현황 문서 갱신 및 근거 중심 최종 보고
