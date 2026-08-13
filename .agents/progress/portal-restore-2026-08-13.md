# AIPOL 포털 운영 복구 — 2026-08-13

## 결과

- `aipol.kaps.or.kr`을 공개 정적 포털로 복구했다.
- `session.aipol.kaps.or.kr`은 연금개혁 실험·설문·결과·어드민 실행 앱으로 분리했다.
- 공개 포털의 참여·결과·어드민 리다이렉트를 임시 Cloudflare Tunnel 주소에서 정식 세션 도메인으로 교체했다.
- 기존 PostgreSQL 행사 API가 응답하고 행사 상태가 `second_deliberation`임을 확인했다.
- 데이터 유실 징후는 발견되지 않았다.

## 운영 배치

- Azure VM: `aipol-app-vm` (`rg_aipol`)
- 공개 포털 릴리스: `/var/www/aipol-portal/releases/20260813-portal-restore-1`
- 공개 포털 현재 링크: `/var/www/aipol-portal/current`
- 실행 앱: `aipol-app.service`, `127.0.0.1:3210`
- nginx 이전 설정 백업: `/etc/nginx/sites-available/aipol-app.pre-portal-restore-20260813`

## 외부 검증

아래 경로가 모두 HTTP 200을 반환했다.

- `https://aipol.kaps.or.kr/`
- `https://aipol.kaps.or.kr/project/`
- `https://aipol.kaps.or.kr/cases/`
- `https://aipol.kaps.or.kr/cases/pension/`
- `https://aipol.kaps.or.kr/cases/pension/experiment/?event=kaps-2026-pension`
- `https://session.aipol.kaps.or.kr/cases/pension/experiment/?event=kaps-2026-pension`
- `https://session.aipol.kaps.or.kr/cases/pension/experiment/results/?event=kaps-2026-pension`
- `https://session.aipol.kaps.or.kr/cases/pension/experiment/admin/`
- `https://session.aipol.kaps.or.kr/api/events/kaps-2026-pension`

추적 이슈: `nextain/pension-policy-lab#5` (완료)
