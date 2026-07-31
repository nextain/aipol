# AIPOL 대외 사이트

AIPOL 전체 프로젝트를 소개하는 정적 사이트다. 시민 응답과 진행자 기능이 있는 `event-tool/`과
별도이며, 이 폴더에는 참가자 데이터·인증·AI 키가 없다.

## 로컬 미리보기

저장소 루트에서 실행한다.

```bash
python -m http.server 8200 --directory site
```

브라우저에서 <http://127.0.0.1:8200>을 연다.

## 공개 상태

- 공개 연구·프로젝트 페이지는 검색엔진 색인을 허용한다.
- 공개 HTML: `index,follow`와 큰 이미지 미리보기 허용
- `robots.txt`: 공개 경로 크롤링 허용 + `sitemap.xml` 안내
- `/cases/pension/experiment/`: 검토 중인 입력 도구이므로 `noindex,nofollow,noarchive` 유지
- Azure Static Web Apps와 Vercel은 실험 도구 경로에만 `X-Robots-Tag` 차단 헤더 적용
- Google Search Console·네이버 서치어드바이저에 사이트맵을 제출할 수 있다.

검색 노출 여부는 접근 통제나 보안 기능이 아니다. 공개할 수 없는 자료는 `site/`에 복사하지 않는다.

## 콘텐츠 상태

2026-08-12 한국정책학회 첫 현장 실증 전까지 연금 사례는 미래 시제로 유지한다. 날짜가 지났다는
이유만으로 자동 전환하지 않고, `/status/`의 행사 후 체크리스트에 따라 실제 실행 기록을 검토한 뒤
수동으로 고친다.

## 배포 대상

Azure Static Web Apps에서 `site/`를 빌드 없이 그대로 배포한다. 기본 주소는
`https://thankful-mushroom-0a2112e00.7.azurestaticapps.net`, 대외 주소는
`https://aipol.kaps.or.kr`다. Vercel 프로젝트는 장애 시 재전환할 수 있는 예비 배포로 유지한다.
대외 사이트와 동적 행사 운영 서비스는 리소스·URL·데이터 저장소를 분리한다.

미공개 정책안이나 내부 운영 자료에서 파생된 보고서·다운로드는 대외 사이트에 두지 않는다. 합성
검증 결과도 입력 자료의 공개 상태와 재현 가능성을 확인한 뒤 별도 사람 검토를 거쳐 공개한다.
