import configparser
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import SpreadsheetNotFound
from gspread.utils import rowcol_to_a1
from playwright.sync_api import sync_playwright

from naverLogin import (
    ensure_logged_in,
    setup_login_profile,
)

KST = timezone(timedelta(hours=9))
API_URL_KEYWORDS = ("booking", "reservation")
DIAG_LEVEL = ((os.getenv("ONEUL_DIAG") or "runtime").strip().lower() or "runtime")
DIAG_ALL = DIAG_LEVEL == "all"
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONF_PATH = PROJECT_DIR.parent / "oneulhair.conf"
EDGE_CHANNEL = "msedge"


def _expand_path(path_value: str):
    """환경변수/사용자 홈(~)을 확장한 경로 문자열을 반환합니다."""
    return os.path.expandvars(os.path.expanduser(path_value.strip()))


def _resolve_config_path(conf_path: str = ""):
    """설정 파일 경로를 결정합니다. 기본값은 프로젝트 상위 폴더의 oneulhair.conf 입니다."""
    env_conf = _expand_path(os.getenv("ONEUL_CONF_PATH", ""))
    raw = (env_conf or conf_path or str(DEFAULT_CONF_PATH)).strip()
    candidate = Path(_expand_path(raw))
    if not candidate.is_absolute():
        candidate = (PROJECT_DIR / candidate).resolve()
    return candidate


def _resolve_path_from_conf(conf_file_path: Path, raw_path: str):
    """conf 파일 기준으로 상대 경로를 절대 경로로 변환합니다."""
    expanded = _expand_path(raw_path or "")
    if not expanded:
        return ""
    path_obj = Path(expanded)
    if not path_obj.is_absolute():
        path_obj = conf_file_path.parent / path_obj
    return str(path_obj.resolve())


def _get_first_option(parser, sections, option, fallback=""):
    """여러 섹션 중 첫 번째로 존재하는 옵션 값을 반환합니다."""
    for section in sections:
        if parser.has_option(section, option):
            return parser.get(section, option, fallback=fallback).strip()
    return fallback


def _parse_yyyymmdd(value: str):
    """YYYYMMDD 문자열을 date로 파싱하고 실패 시 None을 반환합니다."""
    text = (value or "").strip()
    if not text:
        return None
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except Exception:
        return None


def _current_month_date_range_kst():
    """현재 월의 시작일/말일(date)을 KST 기준으로 반환합니다."""
    now_kst = datetime.now(KST)
    first_day = now_kst.date().replace(day=1)
    if first_day.month == 12:
        next_month_first = first_day.replace(year=first_day.year + 1, month=1, day=1)
    else:
        next_month_first = first_day.replace(month=first_day.month + 1, day=1)
    last_day = next_month_first - timedelta(days=1)
    return first_day, last_day


def _to_iso_utc_z(dt_obj: datetime):
    """timezone-aware datetime을 UTC ISO 8601(Z) 문자열로 변환합니다."""
    return dt_obj.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resolve_rest_datetime_iso_utc(start_yyyymmdd: str, end_yyyymmdd: str):
    """설정값(YYYYMMDD)을 UTC ISO 8601 start/endDateTime으로 변환합니다."""
    default_start, default_end = _current_month_date_range_kst()
    start_date = _parse_yyyymmdd(start_yyyymmdd) or default_start
    end_date = _parse_yyyymmdd(end_yyyymmdd) or default_end

    start_dt_kst = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=KST)
    end_dt_kst = datetime(end_date.year, end_date.month, end_date.day, 23, 50, 0, tzinfo=KST)
    return _to_iso_utc_z(start_dt_kst), _to_iso_utc_z(end_dt_kst)


def _upsert_rest_datetime_query(rest_url: str, start_iso_utc: str, end_iso_utc: str):
    """rest_url 쿼리에서 start/endDateTime을 제거 후 맨 뒤에 다시 추가합니다."""
    if not rest_url:
        return rest_url

    parsed = urlparse(rest_url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    pairs = [(k, v) for k, v in pairs if k not in {"startDateTime", "endDateTime"}]
    pairs.append(("startDateTime", start_iso_utc))
    pairs.append(("endDateTime", end_iso_utc))

    return parsed._replace(query=urlencode(pairs, doseq=True)).geturl()


def _load_config(conf_path: str = ""):
    """설정 파일을 읽고 필요한 값을 반환합니다."""
    conf_file = _resolve_config_path(conf_path)
    if not conf_file.exists():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {conf_file} "
            f"(기본 경로: {DEFAULT_CONF_PATH}, override: ONEUL_CONF_PATH)"
        )

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(str(conf_file), encoding="utf-8-sig")

    project_name = parser.get("project", "name", fallback="oneulHair").strip() or "oneulHair"

    booking_url = parser.get("naver", "booking_url")
    rest_url = parser.get("naver", "rest_url", fallback="").strip()
    start_date_cfg = parser.get("naver", "startDateTime", fallback="").strip()
    end_date_cfg = parser.get("naver", "endDateTime", fallback="").strip()
    sheet_fields = [x.strip() for x in parser.get("naver", "sheet_fields", fallback="").split(",") if x.strip()]
    json_fields = [x.strip() for x in parser.get("naver", "json_fields", fallback="").split(",") if x.strip()]
    start_iso_utc, end_iso_utc = _resolve_rest_datetime_iso_utc(start_date_cfg, end_date_cfg)
    rest_url = _upsert_rest_datetime_query(rest_url, start_iso_utc, end_iso_utc)
    service_account_file_raw = (
        os.getenv("ONEUL_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        or parser.get("google", "service_account_file", fallback="").strip()
    )
    service_account_file = _resolve_path_from_conf(conf_file, service_account_file_raw)
    spreadsheet_name = parser.get("google", "spreadsheet_name", fallback="").strip() or project_name

    configured_browser = parser.get(
        "browser",
        "browser_name",
        fallback=parser.get("browser", "browser", fallback="edge"),
    ).strip().lower()
    if configured_browser and configured_browser not in {"edge", "msedge", "microsoft-edge"}:
        print(f"[WARN] browser={configured_browser} 설정은 지원하지 않습니다. Edge(msedge)로 고정 실행합니다.")

    browser_channel = EDGE_CHANNEL
    browser_user_data_dir = _resolve_path_from_conf(
        conf_file,
        parser.get(
            "browser",
            "browser_user_data_dir",
            fallback=parser.get(
                "browser",
                "edge_user_data_dir",
                fallback="~/AppData/Local/Microsoft/Edge/User Data",
            ),
        ),
    )
    browser_profile_directory = (
        parser.get(
            "browser",
            "browser_profile_directory",
            fallback=parser.get("browser", "edge_profile_directory", fallback="Default"),
        ).strip()
        or "Default"
    )
    headless = parser.getboolean("browser", "headless", fallback=True)
    naver_id = (
        os.getenv("ONEUL_NAVER_ID", "").strip()
        or _get_first_option(parser, ["naver", "browser"], "naver_id", fallback="")
    )
    naver_pw = (
        os.getenv("ONEUL_NAVER_PW", "").strip()
        or _get_first_option(parser, ["naver", "browser"], "naver_pw", fallback="")
    )
    manual_login_timeout_sec = max(1, parser.getint("browser", "manual_login_timeout_sec", fallback=180))

    return {
        "conf_file": str(conf_file),
        "project_name": project_name,
        "booking_url": booking_url,
        "rest_url": rest_url,
        "sheet_fields": sheet_fields,
        "json_fields": json_fields,
        "start_date_cfg": start_date_cfg,
        "end_date_cfg": end_date_cfg,
        "start_iso_utc": start_iso_utc,
        "end_iso_utc": end_iso_utc,
        "service_account_file": service_account_file,
        "spreadsheet_name": spreadsheet_name,
        "browser_channel": browser_channel,
        "browser_user_data_dir": browser_user_data_dir,
        "browser_profile_directory": browser_profile_directory,
        "headless": headless,
        "naver_id": naver_id,
        "naver_pw": naver_pw,
        "manual_login_timeout_sec": manual_login_timeout_sec,
    }


def _open_sheet_or_print_key_error(service_account_file: str, spreadsheet_name: str):
    """구글 시트 인증/열기 실패 시 안내 메시지를 출력하고 None을 반환합니다."""
    try:
        key_file = Path(service_account_file)
        if not key_file.exists():
            print("구글시트 파일 api키 이상.")
            return None

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(str(key_file), scopes=scopes)
        gc = gspread.authorize(creds)
        try:
            return gc.open(spreadsheet_name)
        except SpreadsheetNotFound:
            print(f"스프레드시트가 없어 새로 생성합니다: {spreadsheet_name}")
            return gc.create(spreadsheet_name)
    except Exception as e:
        print(f"구글시트 연결 실패: {e}")
        return None


def _diag(message: str):
    """진단 로그를 일관된 접두사로 출력합니다."""
    if DIAG_LEVEL not in {"runtime", "all"}:
        return
    if DIAG_LEVEL == "runtime" and "[실행진단" not in (message or ""):
        return
    print(f"[DIAG] {message}")


def _launch_context_with_fallback(playwright_obj, cfg, purpose: str):
    """기본 프로필 persistent context 실행 실패 시 임시 context로 fallback 합니다."""
    launch_args = [f"--profile-directory={cfg['browser_profile_directory']}"]
    base_root = _resolve_browser_user_data_dir(cfg)
    base_root.mkdir(parents=True, exist_ok=True)
    used_fallback = False

    try:
        context = playwright_obj.chromium.launch_persistent_context(
            user_data_dir=str(base_root),
            channel=cfg["browser_channel"],
            headless=cfg["headless"],
            args=launch_args,
        )
        return context, None, "persistent"
    except Exception:
        used_fallback = True

    # headless 환경 + 기본 프로필 잠금/충돌 대응: 임시 세션으로 수집 시도
    try:
        browser = playwright_obj.chromium.launch(channel=cfg["browser_channel"], headless=cfg["headless"])
        context = browser.new_context()
        if used_fallback:
            print(
                f"[WARN] [실행진단/{purpose}] 기본 프로필 실행 실패로 임시 세션으로 계속합니다."
            )
        return context, browser, "ephemeral"
    except Exception as e:
        _diag(f"[실행진단/{purpose}] 임시 context fallback 실패: {e}")
        raise


def _close_context_bundle(context, browser):
    """context/browser 종료를 안전하게 수행합니다."""
    try:
        context.close()
    except Exception as e:
        _diag(f"[실행진단/close] context.close 실패: {e}")
    if browser is not None:
        try:
            browser.close()
        except Exception as e:
            _diag(f"[실행진단/close] browser.close 실패: {e}")


def _extract_by_path_with_meta(data, dot_path: str):
    """점(.) 경로 값과 경로 존재 여부를 함께 반환합니다."""
    if not dot_path:
        return data, True

    current = data
    for key in dot_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return "", False
        else:
            return "", False
    return current, True


def _extract_by_path(data, dot_path: str):
    """점(.) 경로로 JSON 내부 값을 가져옵니다."""
    value, _found = _extract_by_path_with_meta(data, dot_path)
    return value


def _to_kst_datetime_text(value):
    """datetime/ISO 문자열을 한국시간 문자열로 변환합니다."""
    if value in ("", None):
        return value

    dt_obj = None
    if isinstance(value, datetime):
        dt_obj = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            dt_obj = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return value
    else:
        return value

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _format_phone_with_leading_zero(value):
    """전화번호를 010-0000-0000 형태로 정규화합니다."""
    if value in ("", None):
        return value
    raw = str(value).strip()
    if not raw:
        return value

    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw

    # +82/82로 들어온 휴대폰 번호를 국내 형식으로 정규화
    if digits.startswith("82"):
        digits = f"0{digits[2:]}"

    if not digits.startswith("0"):
        digits = f"0{digits}"

    if len(digits) == 11 and digits.startswith("010"):
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"

    if len(digits) == 10 and digits.startswith("01"):
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"

    if len(digits) >= 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:11]}"

    return digits


def _format_blacklist_mark(value):
    """isBlacklist가 True일 때만 O로 표시합니다."""
    if isinstance(value, bool):
        return "O" if value else ""
    text = str(value).strip().lower()
    if text in {"true", "ture", "1", "y", "yes"}:
        return "O"
    return ""


def _normalize_price_value(value):
    """가격 값을 반올림된 숫자(int)로 정규화합니다."""
    if value in ("", None):
        return value
    if isinstance(value, (int, float)):
        return int(round(value))

    text = str(value).strip().replace(",", "")
    if not text:
        return value

    try:
        return int(round(float(text)))
    except Exception:
        digits = re.sub(r"\D", "", text)
        if digits:
            return int(digits)
        return value


def _normalize_field_value(field_name: str, value):
    """필드 이름별 출력 포맷을 정규화합니다."""
    key = (field_name or "").strip().lower()

    if key.endswith("startdatetime"):
        return _to_kst_datetime_text(value)
    if key.endswith("phone") or key.endswith(".tel") or key == "tel":
        return _format_phone_with_leading_zero(value)
    if key.endswith("isblacklist"):
        return _format_blacklist_mark(value)
    if key.endswith("price"):
        return _normalize_price_value(value)
    return value


def _apply_price_currency_format(worksheet, sheet_fields, json_fields):
    """가격 열에 통화 반올림 서식을 적용합니다."""
    price_col_indices = []
    for idx, (sheet_field, json_field) in enumerate(zip(sheet_fields, json_fields), start=1):
        key = (json_field or "").strip().lower()
        label = (sheet_field or "").strip()
        if key.endswith("price") or "가격" in label:
            price_col_indices.append(idx)

    for col_idx in price_col_indices:
        col_letter = rowcol_to_a1(1, col_idx).rstrip("1")
        worksheet.format(
            f"{col_letter}:{col_letter}",
            {"numberFormat": {"type": "CURRENCY", "pattern": "₩#,##0"}},
        )


def _extract_mapped_value(item, field_name: str):
    """json_fields 항목에서 실제 값을 추출합니다."""
    key = (field_name or "").strip()

    # 계산 필드: completedDateTime/cancelledDateTime 조합
    if key == "@booking_state":
        completed = _extract_by_path(item, "completedDateTime")
        cancelled = _extract_by_path(item, "cancelledDateTime")
        cancelled_desc = _extract_by_path(item, "cancelledDesc")
        if completed not in ("", None, [], {}):
            return "완료"
        if cancelled_desc not in ("", None, [], {}):
            return f"취소({str(cancelled_desc).strip()})"
        if cancelled not in ("", None, [], {}):
            return "취소"
        return "결제예정"

    # 계산 필드: payments[0].items의 2번째부터 name을 |로 결합
    if key == "@procedure":
        payment_items = _extract_by_path(item, "payments.0.items")
        if not isinstance(payment_items, list) or len(payment_items) < 2:
            return ""

        names = []
        for entry in payment_items[2:]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if name:
                names.append(name)
        return "|".join(names)

    return _extract_by_path(item, key)


def _extract_business_id_from_url(url: str):
    """URL에서 business/biz id 후보를 추출합니다."""
    if not url:
        return ""

    parsed = urlparse(url)

    path_patterns = [
        r"/businesses/(\d+)",
        r"/bizes/(\d+)",
        r"/biz/(\d+)",
    ]
    for pattern in path_patterns:
        m = re.search(pattern, parsed.path or "", flags=re.IGNORECASE)
        if m:
            return m.group(1)

    query = parse_qs(parsed.query or "")
    candidate_keys = {
        "businessid",
        "business_id",
        "bizid",
        "biz_id",
        "bizesid",
        "bizes_id",
    }
    for key, values in query.items():
        if key.lower() in candidate_keys and values:
            value = str(values[0])
            m = re.search(r"\d+", value)
            if m:
                return m.group(0)

    return ""


def _collect_candidate_business_ids(data, max_nodes: int = 3000, max_ids: int = 20):
    """응답 JSON 내부의 business/biz id 후보를 수집합니다."""
    keys_with_id_hint = {
        "businessid",
        "business_id",
        "bizid",
        "biz_id",
        "bizesid",
        "bizes_id",
    }

    result = set()
    stack = [data]
    visited = 0

    while stack and visited < max_nodes and len(result) < max_ids:
        current = stack.pop()
        visited += 1

        if isinstance(current, dict):
            for key, value in current.items():
                key_lower = str(key).lower()
                key_has_hint = key_lower in keys_with_id_hint or (
                    "business" in key_lower and "id" in key_lower
                )

                if key_has_hint and isinstance(value, (str, int)):
                    m = re.search(r"\d+", str(value))
                    if m:
                        result.add(m.group(0))

                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            for item in current[:100]:
                if isinstance(item, (dict, list)):
                    stack.append(item)

    return sorted(result)


def _diagnose_source_business_id(cfg, payload, source_label: str):
    """기대 business id와 실제 응답 id 후보를 비교해 프로필 혼입 가능성을 진단합니다."""
    if not DIAG_ALL:
        return

    expected_id = _extract_business_id_from_url(cfg.get("rest_url", "")) or _extract_business_id_from_url(
        cfg.get("booking_url", "")
    )
    found_ids = _collect_candidate_business_ids(payload)

    _diag(
        f"[프로필진단/{source_label}] expected_business_id={expected_id or '미확인'}, "
        f"response_business_ids={found_ids if found_ids else '미탐지'}"
    )

    if expected_id and found_ids and expected_id not in found_ids:
        _diag(
            f"[프로필진단/{source_label}] 불일치 감지: 기대 business_id={expected_id}, "
            f"응답 후보={found_ids} -> 다른 프로필/사업장 데이터 가능성"
        )


def _diagnose_field_quality(items, fields):
    """필드별 누락/빈값 비율을 출력해 값 부재와 경로 오류를 분리 진단합니다."""
    if not DIAG_ALL:
        return

    dict_items = [item for item in items if isinstance(item, dict)]
    if not dict_items or not fields:
        return

    total = len(dict_items)
    for field in fields:
        if (field or "").strip().startswith("@"):
            continue

        missing_path = 0
        empty_value = 0
        for item in dict_items:
            value, found = _extract_by_path_with_meta(item, field)
            if not found:
                missing_path += 1
                continue
            if value in ("", None, [], {}):
                empty_value += 1

        _diag(
            f"[필드진단] {field}: total={total}, missing_path={missing_path}, empty_value={empty_value}"
        )

        if missing_path == total:
            _diag(f"[필드진단] {field}: 경로 자체가 없어 '값을 못 불러옴' 가능성이 큼")
        elif missing_path + empty_value == total:
            _diag(f"[필드진단] {field}: 경로는 존재하나 값이 비어 있어 '프로필에 값 없음' 가능성이 큼")


def _collect_items_from_json(data):
    """JSON 내부에서 예약 목록 후보(list[dict])를 자동 탐지합니다."""
    if isinstance(data, list):
        if any(isinstance(x, dict) for x in data):
            return data
        return []

    if not isinstance(data, dict):
        return []

    preferred_keys = {"items", "list", "content", "bookings", "reservations", "results"}
    stack = [("", data)]
    visited = 0
    best_items = []
    best_score = -1

    while stack and visited < 3000:
        path, node = stack.pop()
        visited += 1

        if isinstance(node, dict):
            for key, value in node.items():
                key_lower = str(key).lower()
                next_path = f"{path}.{key}" if path else str(key)
                if isinstance(value, list):
                    has_dict_item = any(isinstance(item, dict) for item in value[:100])
                    if has_dict_item:
                        score = 1
                        if key_lower in preferred_keys:
                            score += 3
                        if "booking" in key_lower or "reservation" in key_lower:
                            score += 2
                        score += min(len(value), 100) / 1000.0
                        if score > best_score:
                            best_score = score
                            best_items = value
                    for child in value[:100]:
                        if isinstance(child, (dict, list)):
                            stack.append((next_path, child))
                elif isinstance(value, dict):
                    stack.append((next_path, value))
        elif isinstance(node, list):
            has_dict_item = any(isinstance(item, dict) for item in node[:100])
            if has_dict_item:
                score = 1 + min(len(node), 100) / 1000.0
                if score > best_score:
                    best_score = score
                    best_items = node
            for child in node[:100]:
                if isinstance(child, (dict, list)):
                    stack.append((path, child))

    return best_items


def _collect_items_from_api_responses(api_responses, cfg):
    """캡처된 XHR/fetch 응답에서 예약 목록을 추출합니다."""
    for candidate in api_responses:
        maybe_items = _collect_items_from_json(candidate["data"])
        if maybe_items:
            if DIAG_ALL:
                _diag(
                    f"[XHR진단] 후보 적중: url={candidate['url']}, "
                    f"items={len(maybe_items)}"
                )
            _diagnose_source_business_id(cfg, candidate["data"], "XHR")
            return maybe_items
        if DIAG_ALL:
            _diag(f"[XHR진단] 후보 미적중: url={candidate['url']}")
    if DIAG_ALL:
        _diag("[XHR진단] 유효한 예약 목록을 찾지 못했습니다.")
    return []


def _resolve_browser_user_data_dir(cfg):
    """Edge user data 경로를 반환합니다."""
    return Path(cfg["browser_user_data_dir"])





def _collect_items_via_browser_once(cfg):
    """브라우저 접근/REST 호출을 수행하고 상태와 아이템 목록을 반환합니다."""
    items = []

    with sync_playwright() as p:
        try:
            context, browser, launch_mode = _launch_context_with_fallback(p, cfg, "collect")
        except Exception as e:
            print(f"브라우저 프로필 실행 실패: {e}")
            return "fatal", [], ""

        page = context.pages[0] if context.pages else context.new_page()
        api_responses = []

        def _response_handler(resp):
            try:
                if resp.request.resource_type not in ("xhr", "fetch"):
                    return
                full_url = (resp.url or "").lower()
                parsed = urlparse(full_url)
                host = (parsed.netloc or "").lower()
                path = (parsed.path or "").lower()

                # sentry/veta 광고 트래픽 등 노이즈 제거
                if any(noise in host for noise in ("sentry.", "veta.", "nam.veta")):
                    return

                allowed_hosts = {"partner.booking.naver.com", "api-partner.booking.naver.com"}
                if host not in allowed_hosts:
                    return

                # 예약 API 후보 경로만 캡처
                if "/api/" not in path and not path.startswith("/v"):
                    return

                if API_URL_KEYWORDS and not any(k in full_url for k in API_URL_KEYWORDS):
                    return
                if resp.status >= 400:
                    _diag(f"[XHR진단] 오류 응답 제외: status={resp.status}, url={resp.url}")
                    return
                body = resp.json()
                if isinstance(body, (dict, list)):
                    api_responses.append({"url": resp.url, "data": body})
                    _diag(f"[XHR진단] 응답 캡처: status={resp.status}, url={resp.url}")
            except Exception as e:
                _diag(f"[XHR진단] response 처리 실패: {e}")
                return

        page.on("response", _response_handler)

        try:
            login_ok, login_reason = ensure_logged_in(page, context, cfg)
            if not login_ok:
                return "login_required", [], login_reason

            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": cfg["booking_url"],
            }

            if cfg["rest_url"]:
                parsed_rest = urlparse(cfg["rest_url"])
                safe_rest_url = f"{parsed_rest.scheme}://{parsed_rest.netloc}{parsed_rest.path}"
                print(f"REST 호출 시작: {safe_rest_url}")
                _diag(
                    f"[REST진단] host={parsed_rest.netloc}, path={parsed_rest.path}, "
                    f"query_length={len(parsed_rest.query or '')}"
                )
                try:
                    resp = context.request.get(cfg["rest_url"], headers=headers, timeout=30000)
                except Exception as e:
                    print(f"REST 호출 실패: {e}")
                    return "fatal", [], ""

                status_code = resp.status
                content_type = resp.headers.get("content-type", "")
                _diag(f"[REST진단] status={status_code}, content_type={content_type}")
                if status_code >= 400:
                    print(f"REST_URL 이상. status={status_code}")
                    if status_code in (401, 403, 429):
                        _diag("[REST진단] 권한/차단 가능성(401/403/429) -> 네이버 세션 또는 접근 제한 점검 필요")
                    _diag("[REST진단] 응답 본문 출력은 민감정보 보호를 위해 생략했습니다.")
                    page.wait_for_timeout(1500)
                    items = _collect_items_from_api_responses(api_responses, cfg)
                    if not items:
                        return "fatal", [], ""
                    print("REST 직접 호출 실패로 브라우저 XHR 응답 데이터를 사용합니다.")
                else:
                    try:
                        data = resp.json()
                        # print("REST JSON 결과:")
                        # print(json.dumps(data, ensure_ascii=False, indent=2))
                        _diagnose_source_business_id(cfg, data, "REST")
                        items = _collect_items_from_json(data)
                        _diag(f"[REST진단] REST JSON에서 추출한 items={len(items)}")
                    except Exception:
                        print("REST_URL 이상. JSON 파싱 실패")
                        _diag("[REST진단] JSON 파싱 실패 -> HTML/비정상 응답 가능성")
                        _diag("[REST진단] 응답 본문 출력은 민감정보 보호를 위해 생략했습니다.")
                        page.wait_for_timeout(1500)
                        items = _collect_items_from_api_responses(api_responses, cfg)
                        if not items:
                            return "fatal", [], ""
                        print("REST JSON 파싱 실패로 브라우저 XHR 응답 데이터를 사용합니다.")

                if not items:
                    page.wait_for_timeout(1500)
                    items = _collect_items_from_api_responses(api_responses, cfg)
                    _diag(f"[REST진단] REST 직접 결과 없음. XHR fallback items={len(items)}")
            else:
                print("rest_url 미설정: 페이지 XHR/fetch 자동 탐지 모드로 진행합니다.")
                items = _collect_items_from_api_responses(api_responses, cfg)
                _diag(f"[REST진단] 자동탐지 결과 items={len(items)}")
        except Exception as e:
            print(f"실행 중 오류: {e}")
            return "fatal", [], ""
        finally:
            _close_context_bundle(context, browser)

    _diag(f"[수집진단] 최종 수집 건수={len(items)}")
    return "ok", items, ""


def main():
    """전체 동작: 예약 페이지 접근 확인 -> REST JSON 조회 -> 월별 시트 기록"""
    try:
        cfg = _load_config()
    except FileNotFoundError as e:
        print(str(e))
        return

    if "--setup-login" in sys.argv:
        setup_login_profile(cfg, _launch_context_with_fallback, _close_context_bundle)
        return

    status, items, login_reason = _collect_items_via_browser_once(cfg)
    if status == "login_required":
        print(login_reason)
        return

    if status != "ok":
        return

    # REST 확인 이후에 구글시트 키 검증을 수행합니다.
    spreadsheet = _open_sheet_or_print_key_error(
        cfg["service_account_file"],
        cfg["spreadsheet_name"],
    )
    if spreadsheet is None:
        return

    month_sheet_name = datetime.now().strftime("%Y-%m")

    try:
        worksheet = spreadsheet.worksheet(month_sheet_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=month_sheet_name, rows=1000, cols=20)

    json_fields = cfg["json_fields"]
    if not json_fields and items and isinstance(items[0], dict):
        json_fields = list(items[0].keys())

    if not json_fields:
        print("기록할 필드가 없습니다. oneulhair.conf의 json_fields를 확인하세요.")
        return

    sheet_fields = cfg["sheet_fields"] if cfg["sheet_fields"] else list(json_fields)
    if len(sheet_fields) != len(json_fields):
        print("oneulhair.conf의 sheet_fields와 json_fields 개수가 다릅니다.")
        return

    _diagnose_field_quality(items, json_fields)
    _apply_price_currency_format(worksheet, sheet_fields, json_fields)

    existing_headers = worksheet.row_values(1)
    if existing_headers != sheet_fields:
        worksheet.update([sheet_fields], "A1")

    if "bookingId" not in json_fields:
        print("oneulhair.conf의 json_fields에 bookingId가 필요합니다.")
        return

    booking_id_idx = json_fields.index("bookingId")
    deduped_by_id = {}
    inserts_without_id = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = [_normalize_field_value(h, _extract_mapped_value(item, h)) for h in json_fields]
        booking_id = str(row[booking_id_idx]).strip() if booking_id_idx < len(row) else ""
        if booking_id:
            deduped_by_id[booking_id] = row
        else:
            inserts_without_id.append(row)

    if not deduped_by_id and not inserts_without_id:
        print("기록할 데이터가 없습니다.")
        return

    existing_id_to_row = {}
    if deduped_by_id:
        # bookingId 컬럼만 조회해 기존 행 매핑을 구성합니다.
        existing_booking_ids = worksheet.col_values(booking_id_idx + 1)
        for row_num, booking_id_cell in enumerate(existing_booking_ids[1:], start=2):
            booking_id = str(booking_id_cell).strip()
            if booking_id and booking_id not in existing_id_to_row:
                existing_id_to_row[booking_id] = row_num

    updates = []
    inserts = list(inserts_without_id)
    for booking_id, row in deduped_by_id.items():
        row_num = existing_id_to_row.get(booking_id)
        if row_num is not None:
            updates.append((row_num, row))
        else:
            inserts.append(row)

    if updates:
        update_requests = []
        for row_num, row in updates:
            range_name = f"{rowcol_to_a1(row_num, 1)}:{rowcol_to_a1(row_num, len(sheet_fields))}"
            update_requests.append({"range": range_name, "values": [row]})
        worksheet.batch_update(update_requests, value_input_option="RAW")

    if inserts:
        worksheet.append_rows(inserts, value_input_option="RAW")

    print(
        f"완료: insert {len(inserts)}건, update {len(updates)}건을 "
        f"'{month_sheet_name}' 시트에 반영했습니다."
    )


if __name__ == "__main__":
    main()
