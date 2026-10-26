# yj-mail — 대표이사 메일 MCP 중계 (Claude Desktop 확장)

대표이사 PC의 Claude Desktop에서 "어제 온 메일 요약해줘"를 쓰기 위한 중계.
도구 `get_mail(days_ago)` 하나가 Tailscale 비공개 주소의 backoffice `GET /api/mail/day`를 호출한다.

```
Claude Desktop → yj-mail(이 확장, 대표이사 PC) → Tailscale → backoffice 서버 → IMAP 4계정
```

- **비밀번호를 갖지 않는다.** 메일 계정 비밀번호는 운영 서버 `.env`에만 있다.
  신원 확인은 Tailscale Serve가 붙이는 사용자 헤더와 `APP_ALLOWED_TAILSCALE_USERS`로 한다.
- **읽기 전용.** 서버가 readonly SELECT + `BODY.PEEK`로 읽어 '읽음' 표시를 바꾸지 않는다.
- 신원 단위는 사람이 아니라 'PC의 Tailscale 로그인'이다. 그 PC에서 도는 프로그램은 누구든 이 API를 부를 수 있다.

## 개발

```powershell
npm install
npm test
```

## 패키징 (`dist/yj-mail.mcpb`, git에 올리지 않음)

```powershell
npm run pack
```

- **코드를 바꾸면 `manifest.json`과 `package.json`의 `version`을 올린 뒤 패키징한다.** 버전이 같으면 설치된 확장이 새것으로 인식되지 않는다.
- `.mcpbignore`의 패턴은 반드시 `/`로 시작(루트 고정)한다. `dist/`처럼 쓰면 `node_modules/**/dist/`까지 빠져 SDK 코드가 없는 패키지가 만들어진다(설치는 되지만 도구 호출 때 죽음).
- 패키징 후 압축을 풀어 단독 실행을 확인한다.

## 대표이사 PC 설치

1. Tailscale이 켜져 있고, 그 계정이 서버 `APP_ALLOWED_TAILSCALE_USERS`에 있는지 확인
2. `yj-mail.mcpb`를 더블클릭 → Claude Desktop 설치 화면에서 서버 주소 확인(기본값: Tailscale 비공개 주소)
3. 새 대화에서 "어제 온 메일 요약해줘"로 확인. 첫 줄의 조회 날짜와 계정별 결과를 본다

## 응답에서 볼 것

| 표시 | 뜻 |
|---|---|
| `읽기 실패` | 그 계정은 아예 못 읽음. '메일 없음'이 아니다 |
| `하루 상한 초과` | 그 계정은 하루 100통을 넘어 최근 것만 포함 |
| `본문 생략: 응답 크기 한도` | 전체 본문이 15만 자를 넘어 이후 메일은 제목·보낸 사람만 포함 |
| 대시보드 서버에 연결하지 못했습니다 | 이 PC의 Tailscale이 꺼졌거나 서버가 꺼짐 |
| `403` | 이 PC의 Tailscale 계정이 허용 목록에 없음 |
| `404` | 서버에 메일 조회 API가 아직 배포되지 않음 |
