from uom_printer.dji_web import (
    DjiWebService,
    DjiDeviceResult,
    _decode_probe_payload,
    _device_probe_script,
    _login_state_from_probe,
    _result_from_probe,
)


class _SignalRecorder:
    def __init__(self) -> None:
        self.values = []

    def emit(self, *values) -> None:
        self.values.append(values)


class _ProbeUrl:
    def host(self) -> str:
        return "service.dji.com"


class _DeferredProbePage:
    def __init__(self) -> None:
        self.callback = None

    def url(self) -> _ProbeUrl:
        return _ProbeUrl()

    def runJavaScript(self, _script, callback) -> None:
        self.callback = callback


def test_stale_dji_probe_cannot_complete_a_new_query() -> None:
    page = _DeferredProbePage()
    harness = type("ProbeHarness", (), {})()
    harness.page = page
    harness._probe_inflight = False
    harness._shutdown = False
    harness._query_active = True
    harness._query_generation = 7
    harness.result_ready = _SignalRecorder()
    harness.status_changed = _SignalRecorder()
    harness.logger = type("Logger", (), {"info": lambda *_args: None})()
    harness._set_login_state = lambda _logged_in: None
    harness._finish_query = lambda: None

    DjiWebService._probe(harness)
    stale_callback = page.callback
    assert stale_callback is not None

    harness._query_generation = 8
    harness._probe_inflight = True
    stale_callback(
        {
            "host": "service.dji.com",
            "path": "/device/detail",
            "productName": "DJI 过期结果",
            "authenticated": True,
        }
    )

    assert harness.result_ready.values == []
    assert harness._probe_inflight is True


def test_device_probe_only_returns_needed_device_fields() -> None:
    script = _device_probe_script()

    assert "selfServiceObj" in script
    assert "baseInfo" in script
    assert "productName" in script
    assert "productNameCn" in script
    assert "productImg" in script
    assert "activeTime" in script
    assert "imageUrl" in script
    assert "authenticated" in script
    assert "Serial(?: Number)?" in script
    assert "Object.keys(value)" in script
    assert "document.cookie" not in script
    assert "localStorage" not in script
    assert "serialNumber" not in script


def test_device_result_requires_a_resolved_product_name() -> None:
    assert _result_from_probe(None) is None
    assert _result_from_probe({"productName": ""}) is None

    assert _result_from_probe(
        {
            "productName": "DJI Avata 360",
            "activeTime": "2026-07-26",
            "imageUrl": "https://example.invalid/demo.png",
        }
    ) == DjiDeviceResult(
        product_name="DJI Avata 360",
        active_time="2026-07-26",
        image_url="https://example.invalid/demo.png",
    )


def test_probe_payload_accepts_webengine_json_string() -> None:
    payload = '{"host":"service.dji.com","path":"/device/detail","productName":"DJI Avata 360","authenticated":true}'

    assert _decode_probe_payload(payload) == {
        "host": "service.dji.com",
        "path": "/device/detail",
        "productName": "DJI Avata 360",
        "authenticated": True,
    }
    assert _result_from_probe(payload) == DjiDeviceResult("DJI Avata 360")
    assert _login_state_from_probe(payload) is True
    assert _decode_probe_payload("") is None
    assert _decode_probe_payload("not-json") is None


def test_detail_device_evidence_wins_over_stale_login_text() -> None:
    assert _login_state_from_probe(
        {
            "host": "service.dji.com",
            "path": "/device/detail",
            "productName": "DJI Avata 360",
            "authenticated": True,
            "needsLogin": True,
        }
    ) is True
    assert _login_state_from_probe(
        {"host": "account.dji.com", "path": "/login", "needsLogin": True}
    ) is False
    assert _login_state_from_probe(None) is None
