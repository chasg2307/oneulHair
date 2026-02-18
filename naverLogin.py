from queue import Empty, Queue
from threading import Thread

from playwright.sync_api import sync_playwright

LOGIN_HELP_MESSAGE = "로그인이 필요합니다. 브라우저에서 로그인 후 다시 시도해 주세요."
DEFAULT_MANUAL_LOGIN_TIMEOUT_SEC = 180


def _warn(message: str):
    print(f"[WARN] {message}")


def _has_credentials(cfg):
    return bool((cfg.get("naver_id") or "").strip() and (cfg.get("naver_pw") or "").strip())


def _has_login_form(page):
    try:
        id_count = page.locator('input[name="id"], #id').count()
        pw_count = page.locator('input[name="pw"], #pw').count()
        return id_count > 0 and pw_count > 0
    except Exception as e:
        _warn(f"로그인 폼 탐지 실패: {e}")
        return False


def _has_auth_cookie(context):
    try:
        cookies = context.cookies()
    except Exception as e:
        _warn(f"인증 쿠키 확인 실패: {e}")
        return False

    auth_cookie_names = {"nid_aut", "nid_ses", "nauth", "nauth.sid"}
    for cookie in cookies:
        if (cookie.get("name") or "").lower() in auth_cookie_names:
            return True
    return False


def _probe_rest_auth(context, cfg):
    """REST가 401/403이면 로그인 필요 상태로 판단합니다."""
    rest_url = (cfg.get("rest_url") or "").strip()
    if not rest_url:
        return True

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": cfg.get("booking_url", ""),
    }

    try:
        resp = context.request.get(rest_url, headers=headers, timeout=15000)
        return resp.status not in (401, 403)
    except Exception:
        _warn("REST 인증 확인 요청 실패(네트워크/세션 문제 가능).")
        return False


def check_booking_login_state(page, context, booking_url: str):
    """booking_url 접근 후 로그인 필요 여부를 판정합니다."""
    if "nid.naver.com" in (booking_url or "").lower():
        return True, "설정오류: booking_url이 로그인 주소입니다."

    try:
        page.goto(booking_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        if "interrupted by another navigation" not in str(e).lower():
            return True, f"페이지 이동 실패: {e}"

    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception as e:
        _warn(f"페이지 로드 상태 확인 실패: {e}")

    page.wait_for_timeout(700)

    current_url = (page.url or "").lower()
    if "new.smartplace.naver.com/terms" in current_url:
        return True, "스마트플레이스 약관 동의가 필요합니다."
    if "nid.naver.com" in current_url:
        return True, f"로그인 페이지로 이동됨: {page.url}"
    if _has_login_form(page):
        return True, "로그인 폼이 감지되었습니다."
    if not _has_auth_cookie(context):
        return True, "인증 쿠키가 없습니다."

    return False, ""


def attempt_login_with_credentials(page, context, cfg):
    """conf 자격증명으로 네이버 로그인을 1회 자동 시도합니다."""
    naver_id = (cfg.get("naver_id") or "").strip()
    naver_pw = (cfg.get("naver_pw") or "").strip()
    booking_url = cfg.get("booking_url", "")

    if not (naver_id and naver_pw):
        return False, "conf에 naver_id/naver_pw가 없습니다."

    login_url = (
        "https://nid.naver.com/nidlogin.login"
        f"?locale=ko-kr&svctype=1&url={booking_url}"
    )
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('input[name="id"], #id', timeout=10000)
        page.wait_for_selector('input[name="pw"], #pw', timeout=10000)

        page.fill("#id", naver_id)
        page.fill("#pw", naver_pw)

        if page.locator("#log\\.login").count() > 0:
            page.click("#log\\.login")
        elif page.locator("button.btn_login").count() > 0:
            page.click("button.btn_login")
        else:
            page.keyboard.press("Enter")

        page.wait_for_timeout(1800)
        login_required, login_reason = check_booking_login_state(page, context, booking_url)
        if login_required:
            return False, login_reason
        return True, ""
    except Exception as e:
        return False, f"자동로그인 예외: {e}"


def _wait_for_enter_with_timeout(timeout_seconds: int):
    """timeout 내 Enter 입력을 기다립니다. 표준입력이 없으면 False를 반환합니다."""
    queue = Queue(maxsize=1)

    def _reader():
        try:
            input()
            queue.put("entered")
        except EOFError:
            queue.put("eof")

    thread = Thread(target=_reader, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        return False, "입력 대기 시간 초과"

    try:
        result = queue.get_nowait()
    except Empty:
        return False, "입력 상태를 확인할 수 없습니다"

    if result == "eof":
        return False, "표준 입력이 없습니다"

    return True, ""


def wait_until_logged_in_once(page, context, booking_url: str, timeout_seconds: int):
    """수동 로그인 확인을 1회만 수행합니다."""
    print(
        f"로그인이 필요합니다. 브라우저에서 로그인한 뒤 {timeout_seconds}초 안에 Enter를 눌러주세요."
    )

    entered, reason = _wait_for_enter_with_timeout(timeout_seconds)
    if not entered:
        return False, reason

    login_required, login_reason = check_booking_login_state(page, context, booking_url)
    if not login_required:
        print("로그인 확인 완료.")
        return True, ""
    return False, login_reason


def ensure_logged_in(page, context, cfg):
    """로그인 상태면 통과하고, 아니면 자동 로그인 1회 후 수동 확인을 진행합니다."""
    login_required, login_reason = check_booking_login_state(page, context, cfg["booking_url"])
    if not login_required and not _probe_rest_auth(context, cfg):
        login_required = True
        login_reason = "세션 인증 확인 실패(REST 401/403 또는 요청 실패)"
    if not login_required:
        return True, ""

    if _has_credentials(cfg):
        auto_success, auto_reason = attempt_login_with_credentials(page, context, cfg)
        if auto_success:
            return True, ""
        login_reason = f"{login_reason} / 자동로그인 실패: {auto_reason}"

    if cfg.get("headless", False):
        return False, LOGIN_HELP_MESSAGE

    timeout_seconds = int(cfg.get("manual_login_timeout_sec") or DEFAULT_MANUAL_LOGIN_TIMEOUT_SEC)
    timeout_seconds = max(1, timeout_seconds)

    manual_success, manual_reason = wait_until_logged_in_once(
        page,
        context,
        cfg["booking_url"],
        timeout_seconds,
    )
    if manual_success:
        return True, ""

    _warn(f"수동 로그인 확인 실패: {manual_reason}")
    return False, LOGIN_HELP_MESSAGE


def setup_login_profile(cfg, launch_context_with_fallback, close_context_bundle):
    """프로필 로그인 상태를 저장합니다."""
    with sync_playwright() as p:
        try:
            cfg_setup = dict(cfg)
            cfg_setup["headless"] = False
            context, browser, _ = launch_context_with_fallback(p, cfg_setup, "setup-login")
        except Exception as e:
            print(f"브라우저 프로필 실행 실패: {e}")
            return False

        page = context.pages[0] if context.pages else context.new_page()
        success, _ = ensure_logged_in(page, context, cfg_setup)
        close_context_bundle(context, browser)

    if success:
        print("메인 프로필 로그인 저장 완료.")
        return True

    print(LOGIN_HELP_MESSAGE)
    return False


__all__ = [
    "ensure_logged_in",
    "setup_login_profile",
]
