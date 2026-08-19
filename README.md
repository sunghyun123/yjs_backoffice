# yjs_backoffice — 경영 대시보드

대표이사가 씽크와이즈 협업 현황과 최근 안 읽은 메일을 한 화면에서 확인하는 전용 대시보드입니다.

> 현재 상태: **납품 버전 서버 배포·1차 사용자 인수 완료, 메일·Grants·재부팅 운영 검증 진행 중**

## 프로젝트 문서

- [구축 기획서](./경영대시보드_기획서.md)
- [개발 진행 현황](./경영대시보드_개발진행현황.md)
- [승인 화면 목업](./경영대시보드_예시화면_v2.html)
- [초기 화면 목업](./경영대시보드_예시화면.html)
- [배포·인수 체크리스트](./배포_체크리스트.md)
- [서버 유지보수·즉시 배포](./서버_유지보수_배포.md)
- [서버 PC Codex 인수인계](./서버PC_Codex_인수인계.md)

## 확정 기술 구성

- 백엔드: Python 3.11+ / FastAPI / uvicorn / PyMySQL
- 프론트엔드: 단일 HTML / 바닐라 JavaScript
- 공유 활동 색인: `thinkwise-wiki/data/wiki_index.db` 읽기 전용 재사용
- 대시보드 자체 데이터: SQLite
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

운영에서는 위키 증분 동기화가 `work_log`를 한 번만 공유 SQLite 색인으로 가져오고, 위키 검색과 대시보드가 같은 값을 파생해 사용합니다. 최초 설치·자동시작·Tailscale 인수 시험은 [배포 체크리스트](./배포_체크리스트.md), 이후 코드 반영은 [서버 유지보수·즉시 배포](./서버_유지보수_배포.md)를 따릅니다.

진행 범위와 남은 실계정·외부 기기 검증은 [개발 진행 현황](./경영대시보드_개발진행현황.md)을 기준으로 확인합니다.
