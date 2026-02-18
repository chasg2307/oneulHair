# oneulHair

네이버 예약 데이터를 수집해 구글 스프레드시트에 적재하는 자동화 프로젝트입니다.

## 주요 기능
- Playwright로 Microsoft Edge 채널(`msedge`) 실행
- 로그인 필요 시 자동 로그인 1회 시도, 실패 시 수동 로그인 유도
- REST URL 호출 후 JSON 파싱
- 구글 스프레드시트의 월별 시트(`YYYY-MM`)에 upsert

## 로컬 개발 실행 (Python 설치 환경)

### 1) 의존성 설치
```bash
python -m pip install -r requirements.txt
```

Edge 채널(`msedge`)은 시스템에 설치된 Microsoft Edge를 사용합니다.

### 2) 설정 파일 준비
기본 설정 파일 경로는 프로젝트 상위 폴더의 `../oneulhair.conf` 입니다.

```powershell
Copy-Item .\oneulhair.conf.example ..\oneulhair.conf
```

필요 시 환경변수로 설정 파일 경로를 강제할 수 있습니다.
```powershell
$env:ONEUL_CONF_PATH="D:\code\oneulhair.conf"
```

필수 설정:
- `naver.sheet_fields`, `naver.json_fields` (1:1 매핑)
- `google.service_account_file` (서비스 계정 키 JSON 경로)
- `google.spreadsheet_name`
- `browser.browser_user_data_dir` (Edge 사용자 데이터 경로)
- `browser.browser_profile_directory` (Edge 프로필 폴더)

### 3) 실행
```bash
python main.py
```

최초 로그인/세션 갱신:
```bash
python main.py --setup-login
```

## 고객 배포 (Python 미설치 PC, PyInstaller --onedir)

### 1) 빌드 PC에서 최초 빌드
```powershell
powershell -ExecutionPolicy Bypass -File .\build_onedir.ps1
```

생성물:
- `release\oneulHair\oneulHair.exe`
- `release\oneulhair.conf` (예시 설정 파일)
- `release\run.bat` (고객 실행 스크립트)

### 1-1) 코드 변경 시 반영 방법
- `PyInstaller --onedir`에서는 코드가 `oneulHair.exe`에 포함되므로 `release` 안의 `main.py`만 교체해도 반영되지 않습니다.
- 코드/설정 로직을 바꿨다면 아래 명령으로 반드시 재빌드하세요.
```powershell
powershell -ExecutionPolicy Bypass -File .\build_onedir.ps1
```
- 배포 시에는 `release` 폴더 전체를 교체하는 것을 권장합니다.

### 2) 고객 전달 전 준비
`release` 폴더에서 다음을 맞춘 뒤 전달합니다.
- `oneulhair.conf` 값 입력
- `service_account_file` 경로 확인
- 서비스 계정 키 JSON 파일 위치 확인

권장 구조:
```text
release\
  oneulhair.conf
  oneulHair.json
  run.bat
  oneulHair\
    oneulHair.exe
```

`oneulhair.conf` 예:
```ini
[google]
service_account_file = ./oneulHair.json
spreadsheet_name = oneulHair
```

### 3) 고객 실행
```bat
run.bat
```

로그인 세팅 모드:
```bat
run.bat --setup-login
```

`run.bat`는 `ONEUL_CONF_PATH`를 자동 설정하므로 `release\oneulhair.conf`를 기준으로 실행됩니다.

## 트러블슈팅

### 설정 파일이 없습니다
예: `설정 파일이 없습니다: D:\code\oneulhair.conf ...`
- `oneulhair.conf` 실제 위치 확인
- 필요 시 `ONEUL_CONF_PATH`로 경로 지정

### 구글시트 파일 api키 이상.
- `google.service_account_file` 경로 오타 확인
- 키 JSON 파일 존재 여부 확인
- JSON 형식/키 값 손상 여부 확인

### 구글시트 연결 실패(권한)
- 서비스 계정 이메일을 대상 스프레드시트 공유에 추가
- Google Drive/Sheets API 활성화 여부 확인

## 보안 권장사항
- `naver_id`, `naver_pw`는 가능하면 파일 대신 환경변수 사용
  - `ONEUL_NAVER_ID`, `ONEUL_NAVER_PW`
- 키 파일 경로도 환경변수 사용 가능
  - `ONEUL_GOOGLE_SERVICE_ACCOUNT_FILE`
- 실제 비밀정보 파일(`oneulhair.conf`, 키 JSON)은 저장소 커밋 금지
