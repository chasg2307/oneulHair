# CONTEXT_INDEX

## 빠른 진입점
- `main.py:130` 설정 로딩 (`_load_config`)
- `main.py:303` 브라우저 종료 처리 (`_close_context_bundle`)
- `main.py:759` 수집 메인 루프 (`_collect_items_via_browser_once`)
- `main.py:834` 실행 엔트리 (`main`)
- `naverLogin.py:42` REST 인증 확인 (`_probe_rest_auth`)
- `naverLogin.py:61` 로그인 상태 판정 (`check_booking_login_state`)
- `naverLogin.py:129` 수동 로그인 타임아웃 입력
- `naverLogin.py:175` 로그인 오케스트레이션 (`ensure_logged_in`)

## 권장 검색 패턴
- 함수 찾기: `rg -n "def 함수명" main.py naverLogin.py`
- 민감 로그 찾기: `rg -n "print\(|resp\.text\(" main.py naverLogin.py`
- 광역 예외 찾기: `rg -n "except Exception" main.py naverLogin.py`
