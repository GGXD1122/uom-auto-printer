import ssl
import urllib.error
import urllib.request

import pytest

from uom_printer import dji_service


def test_https_context_combines_system_and_bundled_ca_store(monkeypatch) -> None:
    loaded: list[str] = []

    class Context:
        def load_verify_locations(self, *, cafile: str) -> None:
            loaded.append(cafile)

    context = Context()
    monkeypatch.setattr(dji_service.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(dji_service.certifi, "where", lambda: "/demo/cacert.pem")
    dji_service._https_context.cache_clear()

    assert dji_service._https_context() is context
    assert loaded == ["/demo/cacert.pem"]
    dji_service._https_context.cache_clear()


def test_https_certificate_failure_is_reported_without_disabling_verification(monkeypatch) -> None:
    request = urllib.request.Request("https://www.dji.com/cn/support")
    context = ssl.create_default_context()
    monkeypatch.setattr(dji_service, "_https_context", lambda: context)

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "demo certificate"))

    monkeypatch.setattr(dji_service.urllib.request, "urlopen", fail)

    with pytest.raises(RuntimeError, match="无法验证大疆官网安全证书"):
        dji_service._open_url(request, 3)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_official_dji_search_prefers_exact_model(monkeypatch) -> None:
    monkeypatch.setattr(
        dji_service,
        "_read_json",
        lambda _url, _timeout: {
            "status": 200,
            "data": [
                {
                    "product": {
                        "results": [
                            {
                                "title": "<em>DJI</em> Avata 2",
                                "slug": "avata-2",
                                "summary": "4K | 沉浸式飞行",
                                "cover": {"small": "avata2.png"},
                            },
                            {
                                "title": "<em>DJI</em> <em>Avata</em> <em>360</em>",
                                "slug": "avata-360",
                                "summary": "8K/60fps HDR | 360°双模式",
                                "cover": {"small": "avata360.png"},
                            },
                        ]
                    }
                }
            ],
        },
    )
    monkeypatch.setattr(dji_service, "_read_image", lambda _url, _timeout: b"png")
    monkeypatch.setattr(
        dji_service,
        "_read_text",
        lambda _url, _timeout: """
            <h3 class="group-list-title">飞行器</h3>
            <h4>起飞重量</h4><div class="detailed-parameter-value">377 克</div>
            <h4>最长飞行时间</h4><div class="detailed-parameter-value">23 分钟<br><sup>实验说明</sup></div>
            <h3 class="group-list-title">图传</h3>
            <h4>图传方案</h4><div class="detailed-parameter-value">O4</div>
        """,
    )
    dji_service.fetch_dji_product.cache_clear()
    product = dji_service.fetch_dji_product("DJI Avata 360")
    assert product is not None
    assert product.title == "DJI Avata 360"
    assert product.product_url.endswith("/product/avata-360")
    assert product.image_url.endswith("/avata360.png")
    assert product.image_bytes == b"png"
    assert product.specs == ("起飞重量：377 克", "最长飞行时间：23 分钟", "图传方案：O4")


def test_spec_compaction_preserves_meaningful_slashes() -> None:
    value = dji_service._compact_spec_value("12 米/秒 / 1/1.3 英寸 CMOS / H.264/H.265")
    assert value == "12 米/秒；1/1.3 英寸 CMOS；H.264/H.265"


def test_support_catalog_parser_reads_complete_product_links_and_deduplicates() -> None:
    products = dji_service.parse_dji_support_catalog(
        """
        <section>
          <a href="/cn/support/product/demo-air"><img alt="DJI Demo Air">了解更多</a>
          <a href="https://www.dji.com/cn/support/product/demo-mini" aria-label="DJI Demo Mini"></a>
          <a href="/cn/support/product/demo-air">重复入口</a>
          <a href="/cn/support/downloads">不是产品</a>
        </section>
        """
    )

    assert [item["slug"] for item in products] == ["demo-air", "demo-mini"]
    assert products[0]["title"] == "DJI Demo Air"
    assert products[1]["url"].endswith("/cn/support/product/demo-mini")


def test_support_catalog_fetch_uses_public_official_page(monkeypatch) -> None:
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(
        dji_service,
        "_read_text",
        lambda url, timeout: seen.append((url, timeout))
        or '<a href="/cn/support/product/demo-air" title="DJI Demo Air"></a>',
    )

    products = dji_service.fetch_dji_support_catalog(timeout=7)

    assert seen == [(dji_service.DJI_SUPPORT_URL, 7)]
    assert products[0]["title"] == "DJI Demo Air"
