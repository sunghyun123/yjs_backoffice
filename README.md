# yjs_backoffice — 경영 대시보드

대표이사가 이번 주 Google Calendar 일정, Drive 최근 수정 파일, 할 일, 씽크와이즈 협업 현황과 최근 안 읽은 메일을 한 화면에서 확인하는 전용 대시보드입니다.

> 현재 상태: **Google Calendar·Drive 코드·의존성 서버 반영 완료, 운영 설정·실계정 연결 대기**

## 프로젝트 문서

- [구축 기획서](./경영대시보드_기획서.md)
- [개발 진행 현황](./경영대시보드_개발진행현황.md)
- [승인 화면 목업](./경영대시보드_예시화면_v2.html)
- [초기 화면 목업](./경영대시보드_예시화면.html)
- [인수인계 · 다음 작업과 서버 배포](./인수인계.md)
- [대표이사 요구 정본](./목표.html)

## 확정 기술 구성

- 백엔드: Python 3.11+ / FastAPI / uvicorn / PyMySQL
- 프론트엔드: 단일 HTML / 바닐라 JavaScript
- 공유 활동 색인: `thinkwise-wiki/data/wiki_index.db` 읽기 전용 재사용
- 대시보드 자체 데이터: SQLite
- 개인 일정·파일: Google Calendar 읽기 전용 + Drive 메타데이터 읽기 전용 OAuth
- 배포: 씽크와이즈 DB에 접근 가능한 상시 가동 Windows 서버 PC / 작업 스케줄러
- 외부 접속: Tailscale Serve 비공개 HTTPS

## 실행

개발 기본값은 별도 서비스에 영향을 주지 않는 데모 데이터 모드입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe run.py
```

브라우저에서 `http://127.0.0.1:8080`을 엽니다. 종료는 실행한 터미널에서 `Ctrl+C`를 누릅니다.

전체 테스트는 다음 명령으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

실데이터 연결 전에는 `.env`에 씽크와이즈 읽기 전용 계정을 설정하고 아래 진단을 실행합니다. 진단 스크립트도 조회만 허용합니다.

```powershell
.\.venv\Scripts\python.exe scripts\validate_phase0.py
```

운영에서는 위키 증분 동기화가 `work_log`를 한 번만 공유 SQLite 색인으로 가져오고, 위키 검색과 대시보드가 같은 값을 파생해 사용합니다. 다음 작업 순서와 서버 반영 절차는 [인수인계](./인수인계.md)를 따릅니다.

## Google Calendar·Drive 1회 연결

Google 연동은 대표이사 개인 계정의 Calendar와 회사 공유 Drive 하나를 대상으로 하며 파일 본문을 다운로드하지 않습니다. 요청 범위는 Calendar 읽기 전용과 Drive 메타데이터 읽기 전용 두 가지뿐입니다. OAuth 갱신 토큰은 Git·SQLite·로그가 아니라 운영 서버 `.env`에만 저장합니다.

1. Google Cloud에서 [Calendar API](https://developers.google.com/workspace/calendar/api/quickstart/python)와 [Drive API](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)를 활성화합니다.
2. OAuth 클라이언트 유형을 `Web application`으로 만들고 승인된 Redirect URI에 `https://<비공개-대시보드>/api/google/oauth/callback`을 등록합니다.
3. 운영 `.env`에 아래 값만 먼저 넣고 `GOOGLE_REFRESH_TOKEN`은 비워 둡니다.

```dotenv
GOOGLE_ENABLED=true
GOOGLE_CLIENT_ID=<Google Cloud Client ID>
GOOGLE_CLIENT_SECRET=<Google Cloud Client Secret>
GOOGLE_REFRESH_TOKEN=
GOOGLE_REDIRECT_URI=https://<비공개-대시보드>/api/google/oauth/callback
GOOGLE_SHARED_DRIVE_ID=<회사 공유 드라이브 ID>
```

공유 드라이브 ID는 Google Drive에서 해당 공유 드라이브를 연 주소의 `/drives/` 뒤 값입니다. 운영 모드에서는 이 값을 필수로 검사해 개인 Drive로 잘못 조회되는 것을 막습니다.

4. 요구사항을 설치하고 대시보드를 재시작한 뒤 화면의 `Google 계정 연결`을 누릅니다. 앱은 [오프라인 액세스 방식](https://developers.google.com/identity/protocols/oauth2/web-server#offline)으로 한 번 동의를 받고 갱신 토큰을 `.env`에 무출력 저장합니다.
5. `scripts/secure_runtime_acl.ps1`로 ACL을 재확인하고 `scripts/verify_delivery.ps1 -RequireProduction`을 실행합니다.

연동 실패는 기존 씽크와이즈·메일·할 일 화면에 전파되지 않습니다. 마지막 성공 데이터가 있으면 그대로 유지하면서 Google 영역만 갱신 실패로 표시합니다.

진행 범위와 남은 실계정·외부 기기 검증은 [개발 진행 현황](./경영대시보드_개발진행현황.md)을 기준으로 확인합니다.
