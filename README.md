# 점심 빙고

회사 앞에서 **점심에 문 여는 매출 상위 24곳**으로 5×5 빙고판을 만들어 주는 작은 웹 서비스입니다.
한 곳 갈 때마다 도장 하나, 가로·세로·대각선 한 줄이면 빙고. 같은 동네 동료는 그달 같은 판을 받고, 내 판을 링크로 보내 진행 상황을 겨룰 수 있습니다.

<https://indosaram.github.io/lunch-bingo/>

## 데이터

- [k-skill 잇플 스킬 `bccard-eatpl-search`](https://github.com/NomaDamas/k-skill/tree/main/bccard-eatpl-search)의 검색 API(k-skill-proxy 경유)를 동네별 도로명·법정동으로 호출합니다 (`areas.json`).
- 카페·주점·베이커리를 빼고, 결제 시각으로 추정한 영업시간이 11:30–13:30을 포함하는 곳만 남긴 뒤 전국 매출 백분위 순 상위 24곳을 고릅니다 (`build.py`).
- 판 배치는 `(동네, 월)` 시드로 섞어 같은 달에는 모두 같은 판을 받습니다.
- GitHub Actions가 매일 05:30 KST에 다시 빌드해 Pages로 배포합니다. **원본 응답은 저장소에 커밋하지 않고**, 화면에 표시할 값만 빌드 산출물에 담습니다.

## 잇플 연결

- 상세 링크는 API가 준 `merUrl`을 **변형 없이** `<a href target="_blank" rel="noopener">`로 엽니다 (`noreferrer` 없음, 추적 파라미터·단축 URL·중간 페이지 없음).
- `<meta name="referrer" content="strict-origin-when-cross-origin">` — 잇플에는 `https://indosaram.github.io/`가 유입 경로로 전달됩니다.
- 서버(빌드)는 검색 API만 호출하고 상세 페이지는 호출하지 않습니다.

eat.pl 잇플 · BC카드 결제 데이터 기반. 이 사이트는 BC카드·eat.pl의 공식 서비스가 아닙니다. MIT License.
