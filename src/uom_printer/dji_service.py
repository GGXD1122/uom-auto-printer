from __future__ import annotations

import html
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser

import certifi


DJI_SEARCH_API = "https://search-api.dji.com/search"
DJI_CDN_ROOT = "https://www-cdn.djiits.com/"
DJI_SUPPORT_URL = "https://www.dji.com/cn/support"
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class DjiProductInfo:
    title: str
    summary: str
    product_url: str
    image_url: str
    image_bytes: bytes = b""
    specs: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _https_context() -> ssl.SSLContext:
    """Trust both the machine certificate store and the bundled Mozilla roots."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def _open_url(request: urllib.request.Request, timeout: int):
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=_https_context())
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise RuntimeError(
                "无法验证大疆官网安全证书，请检查Windows系统时间或网络代理证书后重试。"
            ) from exc
        raise RuntimeError(f"连接大疆官网失败：{reason}") from exc


def _plain_text(value: object) -> str:
    return html.unescape(HTML_TAG_PATTERN.sub("", str(value or ""))).strip()


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _score_product(model_name: str, product: dict) -> tuple[int, int]:
    query = _normalized(model_name)
    title = _normalized(_plain_text(product.get("title")))
    if not query or not title:
        return (-1, 0)
    if query == title:
        return (1000, len(title))
    if query in title or title in query:
        return (700 + min(len(query), len(title)), len(title))
    query_tokens = set(re.findall(r"[a-z]+|\d+", model_name.lower()))
    title_tokens = set(re.findall(r"[a-z]+|\d+", _plain_text(product.get("title")).lower()))
    overlap = len(query_tokens & title_tokens)
    return (overlap * 100, -abs(len(query) - len(title)))


def _read_json(url: str, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        },
    )
    with _open_url(request, timeout) as response:
        return json.load(response)


def _read_image(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        },
    )
    with _open_url(request, timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("image/"):
            return b""
        return response.read(3 * 1024 * 1024 + 1)[: 3 * 1024 * 1024]


def _read_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        },
    )
    with _open_url(request, timeout) as response:
        return response.read(2 * 1024 * 1024 + 1)[: 2 * 1024 * 1024].decode("utf-8", errors="ignore")


class _DjiSpecsParser(HTMLParser):
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.mode = ""
        self.depth = 0
        self.buffer: list[str] = []
        self.group = ""
        self.key = ""
        self.sup_depth = 0
        self.items: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = str(dict(attrs).get("class") or "").split()
        if tag == "sup" and self.mode == "value":
            self.sup_depth += 1
        if not self.mode and tag == "h3" and "group-list-title" in classes:
            self.mode, self.depth, self.buffer = "group", 1, []
            return
        if not self.mode and tag == "h4":
            self.mode, self.depth, self.buffer = "key", 1, []
            return
        if not self.mode and tag == "div" and "detailed-parameter-value" in classes:
            self.mode, self.depth, self.buffer, self.sup_depth = "value", 1, [], 0
            return
        if self.mode:
            if tag == "br" and self.mode == "value" and not self.sup_depth:
                self.buffer.append("\n")
            if tag not in self._VOID_TAGS:
                self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.mode or tag in self._VOID_TAGS:
            return
        if tag == "sup" and self.mode == "value" and self.sup_depth:
            self.sup_depth -= 1
        self.depth -= 1
        if self.depth:
            return
        value = " / ".join(part.strip() for part in "".join(self.buffer).splitlines() if part.strip())
        value = " ".join(value.split()).strip(" /_")
        if self.mode == "group":
            self.group = value
        elif self.mode == "key":
            self.key = value
        elif self.mode == "value" and self.key and value:
            self.items.append((self.group, self.key, value))
        self.mode, self.buffer = "", []

    def handle_data(self, data: str) -> None:
        if self.mode and not (self.mode == "value" and self.sup_depth):
            self.buffer.append(data)


class _DjiSupportCatalogParser(HTMLParser):
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self._active: dict[str, object] | None = None
        self._depth = 0
        self.products: list[dict[str, str]] = []

    @staticmethod
    def _product_identity(href: str) -> tuple[str, str] | None:
        normalized = urllib.parse.urljoin(DJI_SUPPORT_URL, str(href or "").replace("\\/", "/"))
        parsed = urllib.parse.urlparse(normalized)
        if parsed.netloc.lower() not in {"www.dji.com", "dji.com"}:
            return None
        match = re.fullmatch(r"/(?:cn/)?support/product/([^/?#]+)", parsed.path.rstrip("/"))
        if not match:
            return None
        slug = urllib.parse.unquote(match.group(1)).strip()
        if not slug:
            return None
        return slug, f"https://www.dji.com/cn/support/product/{urllib.parse.quote(slug)}"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: str(value or "") for key, value in attrs}
        if self._active is not None:
            if tag == "img":
                alt = _plain_text(values.get("alt"))
                if alt:
                    self._active["texts"].append(alt)  # type: ignore[union-attr]
            if tag not in self._VOID_TAGS:
                self._depth += 1
            return
        if tag != "a":
            return
        identity = self._product_identity(values.get("href", ""))
        if identity is None:
            return
        slug, url = identity
        texts = [
            _plain_text(values.get("aria-label")),
            _plain_text(values.get("title")),
            _plain_text(values.get("data-title")),
        ]
        self._active = {"slug": slug, "url": url, "texts": [item for item in texts if item]}
        self._depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._active is None or tag in self._VOID_TAGS:
            return
        self._depth -= 1
        if self._depth > 0:
            return
        texts = [" ".join(str(item).split()) for item in self._active["texts"] if str(item).strip()]
        title = max(texts, key=len, default="")
        slug = str(self._active["slug"])
        if not title:
            title = " ".join(part.upper() if len(part) <= 3 else part.title() for part in slug.split("-"))
        self.products.append({"title": title, "slug": slug, "url": str(self._active["url"])})
        self._active = None
        self._depth = 0

    def handle_data(self, data: str) -> None:
        if self._active is not None:
            text = _plain_text(data)
            if text:
                self._active["texts"].append(text)  # type: ignore[union-attr]


_CORE_SPEC_PRIORITY = (
    ("飞行器", "起飞重量"),
    ("飞行器", "最长飞行时间"),
    ("飞行器", "最大抗风速度"),
    ("飞行器", "最大水平飞行速度"),
    ("飞行器", "最大起飞海拔高度"),
    ("相机", "影像传感器"),
    ("相机", "录像分辨率"),
    ("感知", "感知系统类型"),
    ("图传", "图传方案"),
    ("图传", "最大信号有效距离（无干扰、无遮挡）"),
)


def _compact_spec_value(value: str, limit: int = 150) -> str:
    # The parser uses whitespace-delimited slashes as line separators. Keep
    # meaningful slashes in units and names such as m/s, 1/1.3 and H.264/H.265.
    cleaned = re.sub(r"\s+/\s+", "；", value).strip("； ")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip("；，, ") + "…"


def _parse_official_specs(document: str) -> tuple[str, ...]:
    parser = _DjiSpecsParser()
    parser.feed(document)
    values = {(group, key): value for group, key, value in parser.items}
    result = []
    for identity in _CORE_SPEC_PRIORITY:
        value = values.get(identity)
        if value:
            result.append(f"{identity[1]}：{_compact_spec_value(value)}")
    return tuple(result)


def parse_dji_support_catalog(document: str) -> list[dict[str, str]]:
    parser = _DjiSupportCatalogParser()
    parser.feed(str(document or ""))
    products: list[dict[str, str]] = []
    seen: set[str] = set()
    for product in parser.products:
        slug = str(product.get("slug") or "").strip().casefold()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        products.append(dict(product))
    products.sort(key=lambda item: (str(item.get("title") or "").casefold(), str(item.get("slug") or "")))
    return products


def fetch_dji_support_catalog(timeout: int = 20) -> list[dict[str, str]]:
    """Read the public DJI support directory without requiring an account."""
    products = parse_dji_support_catalog(_read_text(DJI_SUPPORT_URL, timeout))
    if not products:
        raise RuntimeError("大疆官网没有返回可识别的产品目录。")
    return products


@lru_cache(maxsize=64)
def fetch_dji_product(model_name: str, timeout: int = 12) -> DjiProductInfo | None:
    """Return the closest official DJI product card for a UOM model name."""
    query = str(model_name or "").strip()
    if not query:
        return None
    params = urllib.parse.urlencode(
        {
            "query": query,
            "locale": "zh-CN",
            "region": "CN",
            "page": 1,
            "per_page": 8,
            "search_model": "product",
        }
    )
    data = _read_json(f"{DJI_SEARCH_API}?{params}", timeout)
    groups = data.get("data") or []
    product_group = groups[0].get("product") if groups and isinstance(groups[0], dict) else {}
    products = product_group.get("results") if isinstance(product_group, dict) else []
    candidates = [item for item in (products or []) if isinstance(item, dict)]
    if not candidates:
        return None
    product = max(candidates, key=lambda item: _score_product(query, item))
    if _score_product(query, product)[0] < 100:
        return None

    title = _plain_text(product.get("title"))
    summary = _plain_text(product.get("summary"))
    slug = str(product.get("slug") or "").strip(" /")
    cover = product.get("cover") if isinstance(product.get("cover"), dict) else {}
    cover_path = str(cover.get("small") or "").lstrip("/")
    image_url = f"{DJI_CDN_ROOT}{cover_path}" if cover_path else ""
    image_bytes = b""
    if image_url:
        try:
            image_bytes = _read_image(image_url, timeout)
        except Exception:
            image_bytes = b""
    specs: tuple[str, ...] = ()
    if slug:
        try:
            specs = _parse_official_specs(_read_text(f"https://www.dji.com/cn/{slug}/specs", timeout))
        except Exception:
            specs = ()
    return DjiProductInfo(
        title=title or query,
        summary=summary,
        product_url=f"https://www.dji.com/cn/product/{slug}" if slug else "",
        image_url=image_url,
        image_bytes=image_bytes,
        specs=specs,
    )
