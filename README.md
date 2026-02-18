# oneulHair

간단 자동화 프로젝트입니다.

## 기능
- Playwright(기본 Edge, 선택 시 Chrome)로 네이버 예약 페이지 접속
- 로그인 필요 시 자동 로그인 1회 시도 후, 실패하면 수동 로그인 안내
- REST URL 호출 후 JSON 파싱
- 구글 스프레드시트(프로젝트명) 내 월별 시트(`YYYY-MM`)에 데이터 추가
- 구글시트 키 문제 시 `구글시트 api키 이상.` 출력 후 종료

## 준비
1. 실제 설정 파일은 프로젝트 상위 폴더의 `../aa.conf`를 사용
   - 예시 파일: 저장소의 `aa.conf.example`
   - 필요 시 환경변수 `ONEUL_CONF_PATH`로 경로 override 가능
2. `../aa.conf` 값을 환경에 맞게 수정
   - `naver.sheet_fields`: 시트 헤더 컬럼명(표시명)
   - `naver.json_fields`: JSON 추출 경로(위 `sheet_fields`와 순서 1:1 매핑)
   - `browser.browser`: `edge`(기본) 또는 `chrome`
   - `browser.browser_user_data_dir`: 브라우저 사용자 데이터 경로
   - `browser.browser_profile_directory`: 사용할 프로필 폴더명(기본 `Default`)
   - 비밀정보는 가능하면 환경변수 사용 권장:
     - `ONEUL_NAVER_ID`, `ONEUL_NAVER_PW`
     - `ONEUL_GOOGLE_SERVICE_ACCOUNT_FILE`
3. 서비스 계정 키 JSON 파일 준비 (`google.service_account_file`)
4. 스프레드시트 공유 대상에 서비스 계정 이메일 추가

## 설치
```bash
python -m pip install -r requirements.txt
python -m playwright install
```

## 실행
```bash
python main.py
```

## 로그인 세팅
- 최초 로그인 또는 세션 갱신이 필요할 때:
```bash
python main.py --setup-login
```
- `python main.py` 실행 시 로그인 필요가 감지되면 자동 로그인 1회 시도 후, 실패 시 한 번만 수동 로그인 확인을 요청합니다.
