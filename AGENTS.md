# AGENTS.md

## 목적
- Codex 컨텍스트 토큰 사용 최소화
- 비밀정보/대용량 로그 파일 오픈 방지

## 기본 탐색 순서 (고정)
1. `rg --files`로 파일 목록만 확인
2. `README.md`만 먼저 읽기
3. 변경 대상 파일을 `rg -n`으로 라인 탐색 후, 필요한 범위만 열기

## 파일별 진입 규칙
- 실행 흐름: `main.py`만 우선
- 로그인 이슈: `naverLogin.py`만 우선
- 보안 정책/리뷰: `forbidden.md`만 우선
- 설정 예시: `oneulhair.conf.example`만 우선

## 열람 금지/지연 규칙
- 전체 파일 전체 읽기 금지 (먼저 라인 범위 스캔)
- 상위 폴더 실제 설정(`../oneulhair.conf`)은 사용자 요청 없으면 열람 금지
- 불필요한 재열람 금지 (이미 읽은 구간은 재사용)

## 편집 전 체크
1. 변경 파일 수를 최소화 (가능하면 1~2개)
2. 보안 관련이면 `forbidden.md` 기준 위반 여부 확인
3. 수정 후 `python -m py_compile main.py naverLogin.py`로 빠른 검증
