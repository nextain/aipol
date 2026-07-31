# 개인 국민연금 시뮬레이터 PR #1 통합 상태

상태는 **BLOCKED**다. 이 디렉터리는 외부 소스를 복제하지 않고 검증 결과만 보존한다.

- 원본 PR: `armybonita/2026-Flagship-Session-KAPS-Human-AI-Collaborative-Policy-Lab-#1`
- 검토 commit: `fcbae3c0dab18476e2274f9e4ff91dadeb2db944`
- 검토 subtree: `cc39021bc7d914320064856966734ef377c2a8c8`
- `vinext build`와 렌더 테스트는 별도 감사 worktree에서 통과했다.
- 애플리케이션 계산 코드는 React client state만 사용하며 입력값 전송 API는 발견되지 않았다.

그러나 다음 조건 때문에 AIPOL 참가자 경로에는 연결하지 않는다.

1. 원본과 하위 프로젝트 모두 `LICENSE`/`NOTICE`가 없다.
2. `N-A/N-B/N-C` 정책값과 세율·기대수명·국고부담 값에 출처·기준일·승인이 없다.
3. CSP와 보안 헤더가 없으며 배포 origin 소유권·변경 통제가 승인되지 않았다.
4. `.gitattributes`가 없어 Windows checkout의 셸 스크립트가 CRLF로 변환되어 공식 빌드 명령이 실패한다.
5. 현재 빌드의 렌더 결과에 로컬 절대 경로가 포함될 수 있다.

`pr1-audit.blocked.json`은 감사 시점의 재현 정보를 담는다. 실제 수집을 열려면 라이선스,
승인 정책값, 재현 가능한 산출물, 승인 origin, CSP, 원값 비전송 브라우저 보고서를 새 정본으로
등록하고 그 계산 정본 해시를 E1a 자료와 동결표에 함께 결합해야 한다.

## AIPOL 계산기 연동 계약

PR #1은 아직 아래 `aipol-calculator-return-v2` 계약을 구현하지 않았으므로
`collection_enabled=false`를 유지한다. 단순 계산 화면이나 수동 JSON 복사는 완료 증명으로
간주하지 않는다.

1. AIPOL은 승인된 `launch_url`과 정확히 같은 HTTPS origin만 허용한다.
2. 참가자별 receipt context는 `#aipol_context=<base64url(canonical JSON)>` URL fragment로
   전달한다. fragment는 HTTP 요청과 Referer에 포함되지 않는다.
3. AIPOL은 `noopener,noreferrer`로 계산기를 열며 opener를 보유하지 않는다. fragment context에는
   exact same-origin `return_url`과 무작위 `channel_id`가 들어간다.
4. 계산기는 완료 후 `return_url#aipol_return=...`으로 이동한다. AIPOL의 복귀 페이지가 행사 origin의
   `BroadcastChannel`로 flattened JWS JSON을 전달한다. 자동 전달 미지원 또는 시간초과 때는 사용자가
   계산기에 표시된 서명 영수증을 붙여 넣을 수 있고 서버가 JWS와 행사 context를 최종 검증한다.
5. context 필드는 `experiment_id`, `experiment_version`, `session_id`,
   `participant_pseudonym`, `artifact_id`, `artifact_hash`, `contract_hash`로 고정하며 2 KiB를
   넘을 수 없다. 참가 토큰, 참여 코드, 소득 원값, 이름·연락처 등 민감값을 넣지 않는다.
6. 계산기 origin에서 이 계약의 브라우저 E2E를 통과한 SHA-256 `integration_test_hash`를
   calculation 정본과 E1a artifact 양쪽에 동일하게 결합해야 동결을 열 수 있다.
