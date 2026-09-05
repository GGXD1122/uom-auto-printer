from __future__ import annotations

import base64
import logging

from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from uom_printer.uom_web import UomWebFailure, UomWebService, rank_uom_model_candidates


_TEST_APPLICATION: QApplication | None = None


def _application() -> QApplication:
    global _TEST_APPLICATION
    _TEST_APPLICATION = QApplication.instance() or QApplication([])
    return _TEST_APPLICATION


class _SignalRecorder:
    def __init__(self) -> None:
        self.values: list[tuple[object, ...]] = []

    def emit(self, *values) -> None:
        self.values.append(values)


class _LoginProbeHarness:
    def __init__(self) -> None:
        self._logged_in = True
        self._login_label = "UOM官网已登录"
        self._login_probe_failures = 0
        self.logger = logging.getLogger("test-uom-login-probe")
        self.login_state_changed = _SignalRecorder()

    def _set_login_state(self, logged_in: bool) -> None:
        UomWebService._set_login_state(self, logged_in)


def test_login_probe_unknown_preserves_session_and_requires_three_explicit_failures() -> None:
    harness = _LoginProbeHarness()

    UomWebService._login_probe_result(harness, None)
    UomWebService._login_probe_result(harness, False)
    UomWebService._login_probe_result(harness, False)
    assert harness._logged_in is True
    assert harness.login_state_changed.values == []

    UomWebService._login_probe_result(harness, False)
    assert harness._logged_in is False
    assert harness.login_state_changed.values == [(False, "UOM官网待登录")]


class _RetryUrl:
    def isEmpty(self) -> bool:
        return False

    def scheme(self) -> str:
        return "https"


class _RetryPage:
    def __init__(self) -> None:
        self.actions: list[object] = []

    def url(self) -> _RetryUrl:
        return _RetryUrl()

    def triggerAction(self, action: object) -> None:
        self.actions.append(action)


def test_ensure_loaded_retries_a_failed_https_page_instead_of_staying_stuck() -> None:
    harness = type("RetryHarness", (), {})()
    harness.page = _RetryPage()
    harness._last_load_ok = False
    harness._page_loading = False

    UomWebService.ensure_loaded(harness)

    assert len(harness.page.actions) == 1


def test_transient_transport_error_is_retryable_without_being_called_logout() -> None:
    failure = UomWebService._transport_failure(500, side_effect_possible=False)

    assert isinstance(failure, UomWebFailure)
    assert failure.kind == "network"
    assert failure.outcome_unknown is False


def test_explicit_unauthorized_transport_error_is_classified_as_session_loss() -> None:
    failure = UomWebService._transport_failure(401, side_effect_possible=False)

    assert isinstance(failure, UomWebFailure)
    assert failure.kind == "session"


def test_side_effect_transport_error_requires_result_check_before_retry() -> None:
    failure = UomWebService._transport_failure(0, side_effect_possible=True)

    assert failure.kind == "unknown"
    assert failure.outcome_unknown is True


class _SearchHarness:
    def __init__(self) -> None:
        self.logger = logging.getLogger("test-uom-web")
        self.body = ""
        self.completed = None
        self.failed = None

    def _run_async_script(self, body, success, failure, timeout_ms=25000, **kwargs) -> None:
        self.body = body
        self.completed = success
        self.failed = failure
        self.side_effect_possible = bool(kwargs.get("side_effect_possible", False))


def test_account_search_walks_pages_and_matches_both_identifiers() -> None:
    harness = _SearchHarness()
    results = []
    errors = []

    UomWebService.search_registered_aircraft(
        harness,
        "1581TESTSERIAL",
        results.append,
        errors.append,
    )

    assert "for (let pageNum = 1; pageNum <= maxPages" in harness.body
    assert "pageSize: 500" in harness.body
    assert "offset: (pageNum - 1) * 500" in harness.body
    assert "row.uasCode" in harness.body
    assert "row.chanpxlh" in harness.body
    assert "searchKey" not in harness.body
    harness.completed(
        {
            "rows": [
                {
                    "id": "owned-row",
                    "uasCode": "UAS-DEMO-0001",
                    "chanpxlh": "1581TESTSERIAL",
                }
            ]
        }
    )
    assert errors == []
    assert results[0][0]["id"] == "owned-row"


class _FakeUrl:
    def host(self) -> str:
        return "uom.caac.gov.cn"


class _HangingPage:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def url(self) -> _FakeUrl:
        return _FakeUrl()

    def runJavaScript(self, script, callback=None) -> None:
        self.scripts.append(script)
        # Deliberately never invoke the callback, matching a frozen renderer.


class _AsyncRequestHarness(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.page = _HangingPage()
        self._page_loading = False
        self._request_timers = {}
        self._request_deadline_timers = {}
        self._request_aborters = {}
        self.login_probes = 0

    def _probe_login_state(self) -> None:
        self.login_probes += 1

    def _abort_pending_requests(self, message: str) -> None:
        UomWebService._abort_pending_requests(self, message)


def test_async_web_request_has_wall_clock_timeout_even_when_javascript_never_returns() -> None:
    application = _application()
    harness = _AsyncRequestHarness()
    failures: list[object] = []

    UomWebService._run_async_script(
        harness,
        "return true;",
        lambda _result: None,
        failures.append,
        timeout_ms=25,
    )
    QTest.qWait(80)

    assert len(failures) == 1
    assert isinstance(failures[0], UomWebFailure)
    assert failures[0].kind == "network"
    assert "响应超时" in str(failures[0])
    assert harness._request_timers == {}
    assert harness._request_deadline_timers == {}
    assert harness._request_aborters == {}
    assert application is not None


def test_refresh_aborts_pending_side_effect_request_once_and_releases_state() -> None:
    application = _application()
    harness = _AsyncRequestHarness()
    failures: list[object] = []

    UomWebService._run_async_script(
        harness,
        "return true;",
        lambda _result: None,
        failures.append,
        timeout_ms=5000,
        side_effect_possible=True,
    )
    UomWebService._load_started(harness)
    QTest.qWait(40)

    assert harness._page_loading is True
    assert len(failures) == 1
    assert failures[0].kind == "unknown"
    assert failures[0].outcome_unknown is True
    assert "已刷新或返回" in str(failures[0])
    assert harness._request_timers == {}
    assert harness._request_deadline_timers == {}
    assert harness._request_aborters == {}
    assert application is not None


class _CancellationPage:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def url(self) -> _FakeUrl:
        return _FakeUrl()

    def runJavaScript(self, script, callback=None) -> None:
        self.scripts.append(script)
        if callback is not None:
            callback(True)


class _CancellationHarness:
    def __init__(self, logged_in: bool) -> None:
        self.page = _CancellationPage()
        self._logged_in = logged_in
        self.logger = logging.getLogger("test-uom-cancel")
        self.body = ""
        self.completed = None

    def _run_async_script(self, body, success, failure, timeout_ms=25000, **kwargs) -> None:
        self.body = body
        self.completed = success
        self.failed = failure
        self.timeout_ms = timeout_ms
        self.side_effect_possible = bool(kwargs.get("side_effect_possible", False))


def test_open_cancellation_page_only_navigates_to_official_entry() -> None:
    harness = _CancellationHarness(logged_in=True)
    opened = []
    errors = []

    UomWebService.open_cancellation_page(harness, lambda: opened.append(True), errors.append)

    assert opened == [True]
    assert errors == []
    assert len(harness.page.scripts) == 1
    assert "注销登记" in harness.page.scripts[0]
    assert ".post(" not in harness.page.scripts[0]


def test_open_cancellation_page_requires_current_login() -> None:
    harness = _CancellationHarness(logged_in=False)
    opened = []
    errors = []

    UomWebService.open_cancellation_page(harness, lambda: opened.append(True), errors.append)

    assert opened == []
    assert errors == ["请先在右侧UOM官网登录。"]
    assert harness.page.scripts == []


def test_one_click_cancellation_rechecks_owner_and_submits_transfer_reason() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []
    row = {
        "id": "owned-row-1",
        "uasCode": "UAS-DEMO-0001",
        "chanpxlh": "1581TESTCURRENTACCOUNT",
        "suoyqrlx": "0",
    }

    UomWebService.cancel_registered_aircraft(harness, row, results.append, errors.append)

    assert "/uom-uavreg/uomUavRegist/list" in harness.body
    assert 'zhuangt: "0"' in harness.body
    assert "activeRecord = payload.rows.find" in harness.body
    assert "/uom-uavreg/uomUavRegist/suoyqrData" in harness.body
    assert "/uom-uavreg/uomUavLogout/add" in harness.body
    assert 'zhuxyy: "3"' in harness.body
    assert 'zhuxsm: "所有权变更（出售、转让或赠予等）"' in harness.body
    assert harness.timeout_ms == 35000
    assert harness.side_effect_possible is True
    harness.completed(
        {
            "ok": True,
            "message": "注销成功",
            "uasCode": row["uasCode"],
            "chanpxlh": row["chanpxlh"],
        }
    )
    assert errors == []
    assert results == [
        {
            "message": "注销成功",
            "uasCode": row["uasCode"],
            "chanpxlh": row["chanpxlh"],
        }
    ]


def test_one_click_cancellation_rejects_incomplete_or_logged_out_record() -> None:
    logged_out = _CancellationHarness(logged_in=False)
    errors = []
    UomWebService.cancel_registered_aircraft(
        logged_out,
        {"id": "owned-row-1", "uasCode": "UAS-DEMO-0001"},
        lambda _result: None,
        errors.append,
    )
    assert errors == ["请先在右侧UOM官网登录。"]
    assert logged_out.body == ""

    logged_in = _CancellationHarness(logged_in=True)
    errors.clear()
    UomWebService.cancel_registered_aircraft(
        logged_in,
        {"uasCode": "UAS-DEMO-0001"},
        lambda _result: None,
        errors.append,
    )
    assert errors == ["当前实名记录缺少必要标识，请重新查询后再试。"]
    assert logged_in.body == ""


def test_personal_registration_context_uses_official_wechat_face_flow() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []

    UomWebService.fetch_personal_registration_context(
        harness,
        results.append,
        errors.append,
    )

    assert "/common/getUserAge" in harness.body
    assert "/uom-uavreg/uomUavRegist/suoyqrData" in harness.body
    assert '"/enumData/list"' in harness.body
    assert "EM_NATURAL_TYPE_IN" in harness.body
    assert '{ biztype: "EM_NATURAL_TYPE",' not in harness.body
    assert "/home/anon/" not in harness.body
    assert "faceDetectStateDisable" not in harness.body
    assert 'const requestedFaceProvider = "wx"' in harness.body
    assert "/wx/getWxaCode?type=" in harness.body
    assert '"&JTOKENID=" + encodeURIComponent(authToken)' in harness.body
    assert "window.Base64.encode" in harness.body
    assert "detectImageMime" in harness.body
    assert 'return "image/jpeg"' in harness.body
    assert 'return "image/png"' in harness.body
    assert 'new Blob([buffer], { type: mime })' in harness.body
    assert 'qrResponse.headers.get("content-type")' in harness.body
    assert "faceProvider," in harness.body
    assert "maskedIdentity" not in harness.body
    assert "\\d{17}" not in harness.body
    for forbidden_business_request in (
        "/uomCompanyInfo/list",
        "/uom-uavreg/uomUavModel/listSelect",
        "/uomAttachment/upload",
        "/uom-uavreg/uomUavRegist/add",
    ):
        assert forbidden_business_request not in harness.body
    assert harness.timeout_ms == 35000
    harness.completed(
        {
            "ok": True,
            "owner": {
                "xingm": "演示用户",
                "zhengjlx": "0",
                "zhengjhm": "11010119900101001X",
                "shoujhm": "DEMO-PHONE",
                "dianzyx": "demo@example.invalid",
                "uid": "demo-uid",
                "eid": "demo-eid",
            },
            "faceProvider": "wx",
            "availableFaceProviders": [
                {"value": "wx", "title": "微信小程序", "remark": "微信APP"},
                {"value": "zfb", "title": "支付宝小程序", "remark": "支付宝APP"},
            ],
            "faceQrDataUrl": "data:image/png;base64,DEMO",
        }
    )
    assert errors == []
    assert results[0]["faceProvider"] == "wx"
    assert [item["value"] for item in results[0]["availableFaceProviders"]] == ["wx", "zfb"]
    assert results[0]["faceQrDataUrl"].startswith("data:image/")


def test_personal_registration_context_can_request_official_alipay_channel() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []

    UomWebService.fetch_personal_registration_context(
        harness,
        results.append,
        errors.append,
        provider="zfb",
    )

    assert 'const requestedFaceProvider = "zfb"' in harness.body
    assert "availableValues.includes(requestedFaceProvider)" in harness.body
    assert errors == []


def test_personal_registration_context_accepts_official_display_masking() -> None:
    masked = _CancellationHarness(logged_in=True)
    masked_results: list[dict] = []
    masked_errors: list[str] = []
    UomWebService.fetch_personal_registration_context(
        masked,
        masked_results.append,
        masked_errors.append,
    )
    masked.completed(
        {
            "ok": True,
            "owner": {
                "xingm": "演**户",
                "zhengjlx": "0",
                "zhengjhm": "110101********001X",
            },
            "faceProvider": "wx",
            "availableFaceProviders": [{"value": "wx"}],
            "faceQrDataUrl": "data:image/png;base64,DEMO",
        }
    )
    assert masked_errors == []
    assert masked_results[0]["owner"]["zhengjhm"] == "110101********001X"

    invalid = _CancellationHarness(logged_in=True)
    invalid_results: list[dict] = []
    invalid_errors: list[str] = []
    UomWebService.fetch_personal_registration_context(
        invalid,
        invalid_results.append,
        invalid_errors.append,
    )
    invalid.completed(
        {
            "ok": True,
            "owner": {
                "xingm": "演示用户",
                "zhengjlx": "0",
                "zhengjhm": "DEMO-CERT",
            },
            "faceProvider": "wx",
            "availableFaceProviders": [{"value": "wx"}],
            "faceQrDataUrl": "data:image/png;base64,DEMO",
        }
    )
    assert invalid_errors == []
    assert invalid_results[0]["owner"]["zhengjhm"] == "DEMO-CERT"


def test_wechat_face_poll_only_accepts_official_success_code_four() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []
    owner = {
        "xingm": "演示用户",
        "zhengjlx": "0",
        "zhengjhm": "11010119900101001X",
    }

    UomWebService.poll_wechat_face_verification(
        harness,
        owner,
        results.append,
        errors.append,
    )

    assert '"/home/faceDetectState"' in harness.body
    assert "/home/anon/" not in harness.body
    assert '"provider": "wx"' in harness.body
    assert "type: requested.provider" in harness.body
    assert "certNum:" in harness.body
    assert "completed: code === 4" in harness.body
    assert "started: code === 1 || code === 2 || code === 3" in harness.body
    harness.completed({"ok": True, "completed": False, "started": True, "code": 2})
    harness.completed({"ok": True, "completed": True, "started": False, "code": 4})
    assert errors == []
    assert results == [
        {"completed": False, "started": True, "code": 2},
        {"completed": True, "started": False, "code": 4},
    ]


def test_face_poll_passes_official_display_masking_to_official_endpoint() -> None:
    harness = _CancellationHarness(logged_in=True)
    results: list[dict] = []
    errors: list[str] = []

    UomWebService.poll_face_verification(
        harness,
        {"xingm": "演示用户", "zhengjlx": "0", "zhengjhm": "110101********001X"},
        "wx",
        results.append,
        errors.append,
    )

    assert errors == []
    assert '"zhengjhm": "110101********001X"' in harness.body
    assert '"/home/faceDetectState"' in harness.body
    harness.completed({"ok": True, "completed": False, "started": True, "code": 2})
    assert results == [{"completed": False, "started": True, "code": 2}]


def test_official_brand_model_query_requires_one_exact_selectable_record() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []

    UomWebService.fetch_official_brand_model(
        harness,
        "演示厂商",
        "演示无人机",
        results.append,
        errors.append,
        model_code="DEMO-MODEL",
    )

    assert "/uomCompanyInfo/list" in harness.body
    assert 'unitDanwlx: "02"' in harness.body
    assert "/uom-uavreg/uomUavModel/listSelect" in harness.body
    assert "for (let pageNum = 1; pageNum <= maxPages" in harness.body
    assert "pageSize = 100" in harness.body
    assert "offset: (pageNum - 1) * pageSize" in harness.body
    assert 'String(row.dataState || "") !== "1"' in harness.body
    assert harness.timeout_ms == 45000
    harness.completed(
        {
            "ok": True,
            "manufacturer": {
                "id": "demo-company-id",
                "unitName": "演示厂商",
                "unitUsccode": "DEMO-USCC",
            },
            "models": [
                {
                    "id": "demo-model-id",
                    "chanpxh": "DEMO-MODEL",
                    "chanpmc": "演示无人机",
                    "dataState": "0",
                }
            ],
        }
    )
    assert errors == []
    assert results[0]["model"]["chanpxh"] == "DEMO-MODEL"


def test_official_brand_model_query_returns_ambiguous_candidates_for_manual_selection() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []

    UomWebService.fetch_official_brand_model(
        harness,
        "演示厂商",
        "演示无人机",
        results.append,
        errors.append,
    )
    harness.completed(
        {
            "ok": True,
            "manufacturer": {"id": "demo-company-id", "unitName": "演示厂商"},
            "models": [
                {
                    "id": "demo-model-a",
                    "chanpxh": "DEMO-A",
                    "chanpmc": "演示无人机",
                    "kongjzl": "0.45",
                    "zuidqfzl": "0.47",
                },
                {
                    "id": "demo-model-b",
                    "chanpxh": "DEMO-B",
                    "chanpmc": "演示无人机",
                    "kongjzl": "0.46",
                    "zuidqfzl": "0.49",
                },
            ],
        }
    )

    assert errors == []
    assert results[0]["ambiguous"] is True
    assert [item["chanpxh"] for item in results[0]["candidates"]] == ["DEMO-A", "DEMO-B"]


def test_model_ranker_never_auto_accepts_unknown_sales_suffix() -> None:
    resolution = rank_uom_model_candidates(
        "DJI 演示机型 X1 增强图传",
        [
            {
                "id": "demo-model-x1",
                "chanpxh": "DEMO-X1",
                "chanpmc": "DJI 演示机型 X1",
                "dataState": "0",
            },
            {
                "id": "demo-model-x2",
                "chanpxh": "DEMO-X2",
                "chanpmc": "DJI 演示机型 X2",
                "dataState": "0",
            },
        ],
    )

    assert resolution["ok"] is True
    assert resolution["ambiguous"] is True
    assert resolution["candidates"][0]["chanpxh"] == "DEMO-X1"


def test_model_ranker_auto_accepts_only_name_confirmed_by_both_official_sources() -> None:
    models = [
        {
            "id": "demo-model-x1",
            "chanpxh": "DEMO-X1",
            "chanpmc": "大疆 DJI 演示机型 X1",
            "dataState": "0",
        }
    ]

    confirmed = rank_uom_model_candidates(
        "DJI 演示机型 X1",
        models,
        official_product_names=["DJI 演示机型 X1", "DJI 其他产品"],
    )
    stale_catalog = rank_uom_model_candidates(
        "DJI 演示机型 X1",
        models,
        official_product_names=["DJI 其他产品"],
    )

    assert confirmed["ambiguous"] is False
    assert confirmed["matchType"] == "official_catalog_name_exact"
    assert stale_catalog["ambiguous"] is True
    assert stale_catalog["matchType"] == "unverified_exact_name"


def test_model_ranker_returns_nearby_candidates_when_unique_match_is_not_safe() -> None:
    resolution = rank_uom_model_candidates(
        "DJI 演示机型 X Pro 套装",
        [
            {
                "id": "demo-model-a",
                "chanpxh": "DEMO-X-A",
                "chanpmc": "DJI 演示机型 X Pro",
                "dataState": "0",
            },
            {
                "id": "demo-model-b",
                "chanpxh": "DEMO-X-B",
                "chanpmc": "DJI 演示机型 X Pro",
                "dataState": "0",
            },
            {
                "id": "demo-model-y",
                "chanpxh": "DEMO-Y",
                "chanpmc": "DJI 演示机型 Y",
                "dataState": "0",
            },
        ],
    )

    assert resolution["ok"] is True
    assert resolution["ambiguous"] is True
    assert [item["chanpxh"] for item in resolution["candidates"]] == ["DEMO-X-A", "DEMO-X-B"]


def test_model_ranker_still_returns_manual_fallback_for_unfamiliar_future_name() -> None:
    resolution = rank_uom_model_candidates(
        "DJI 未来演示产品 Z9",
        [
            {
                "id": "demo-model-a",
                "chanpxh": "DEMO-A",
                "chanpmc": "DJI 演示产品 A9",
                "dataState": "0",
            },
            {
                "id": "demo-model-b",
                "chanpxh": "DEMO-B",
                "chanpmc": "DJI 演示产品 B9",
                "dataState": "0",
            },
        ],
    )

    assert resolution["ok"] is True
    assert resolution["ambiguous"] is True
    assert resolution["candidates"]


def test_registration_photo_upload_uses_file_multipart_and_auth_token() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []
    jpeg = base64.b64encode(b"\xff\xd8\xffDEMO-JPEG\xff\xd9").decode("ascii")

    UomWebService.upload_registration_photo(
        harness,
        jpeg,
        "demo-front.jpg",
        results.append,
        errors.append,
    )

    assert "/uomAttachment/quotecode/get" in harness.body
    assert 'multipart.append("file", file)' in harness.body
    assert "Authorization: token" in harness.body
    assert "/uomAttachment/upload/" in harness.body
    assert "/uomAttachment/list/" in harness.body
    assert harness.timeout_ms == 60000
    harness.completed(
        {
            "ok": True,
            "quoteCode": "DEMO-QUOTE",
            "attachmentId": "DEMO-ATTACHMENT",
            "fileName": "demo-front.jpg",
        }
    )
    assert errors == []
    assert results == [
        {
            "quoteCode": "DEMO-QUOTE",
            "attachmentId": "DEMO-ATTACHMENT",
            "fileName": "demo-front.jpg",
        }
    ]


def test_registration_photo_upload_rejects_non_jpeg_before_web_request() -> None:
    harness = _CancellationHarness(logged_in=True)
    errors = []

    UomWebService.upload_registration_photo(
        harness,
        base64.b64encode(b"not-a-jpeg").decode("ascii"),
        "demo.jpg",
        lambda _result: None,
        errors.append,
    )

    assert errors == ["待上传照片不是有效的JPEG图片。"]
    assert harness.body == ""


def _demo_personal_registration_form() -> dict:
    return {
        "xingm": "演示用户",
        "zhengjlx": "0",
        "zhengjhm": "DEMO-CERT",
        "shoujhm": "DEMO-PHONE",
        "dianzyx": "demo@example.invalid",
        "uid": "demo-uid",
        "eid": "demo-eid",
        "shengccsmc": "演示厂商",
        "shengccsid": "demo-company-id",
        "chanpxh": "DEMO-MODEL",
        "chanpxhid": "demo-model-id",
        "chanpmc": "演示无人机",
        "chanplb": "1",
        "chanplx": "1",
        "kongjzl": "0.455",
        "zuidqfzl": "0.468",
        "chanpxlh": "DEMO-SERIAL-0001",
        "mfgDate": "2026-07-26",
        "tup1": "DEMO-QUOTE-FRONT",
        "tup2": "DEMO-QUOTE-SERIAL",
        "shiyyt": ["02", "01"],
        "tongxfs": ["2", "1"],
    }


def test_personal_registration_submits_confirmed_form_then_updates_product_number() -> None:
    harness = _CancellationHarness(logged_in=True)
    results = []
    errors = []

    UomWebService.submit_personal_registration(
        harness,
        _demo_personal_registration_form(),
        results.append,
        errors.append,
    )

    assert "/uom-uavreg/uomUavRegist/add" in harness.body
    assert "/uom-uavreg/uomProductNumber/update?productNumber=" in harness.body
    assert '"suoyqrlx": "0"' in harness.body
    assert '"wurjzl": "0"' in harness.body
    assert '"numberType": "1"' in harness.body
    assert '"chanpsbm": ""' in harness.body
    assert '"shiyyt": "[\\"01\\",\\"02\\"]"' in harness.body
    assert '"tongxfs": "[\\"1\\",\\"2\\"]"' in harness.body
    assert "Promise.race" in harness.body
    assert "1500" in harness.body
    assert harness.timeout_ms == 45000
    assert harness.side_effect_possible is True
    harness.completed(
        {
            "ok": True,
            "id": "DEMO-REGISTRATION-ID",
            "message": "注册成功",
            "productNumberUpdated": True,
            "productNumberUpdatePending": False,
            "submitElapsedMs": 820,
            "syncElapsedMs": 110,
        }
    )
    assert errors == []
    assert results == [
        {
            "id": "DEMO-REGISTRATION-ID",
            "message": "注册成功",
            "productNumberUpdated": True,
            "productNumberUpdatePending": False,
            "submitElapsedMs": 820,
            "syncElapsedMs": 110,
        }
    ]


def test_personal_registration_rejects_incomplete_form_before_submit() -> None:
    harness = _CancellationHarness(logged_in=True)
    form = _demo_personal_registration_form()
    del form["tup2"]
    errors = []

    UomWebService.submit_personal_registration(
        harness,
        form,
        lambda _result: None,
        errors.append,
    )

    assert errors == ["实名登记表单缺少必填字段：tup2"]
    assert harness.body == ""
