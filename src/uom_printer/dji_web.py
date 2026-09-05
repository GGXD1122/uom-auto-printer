from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from shiboken6 import delete

from .diagnostics import get_logger
from .paths import app_data_dir


DJI_DEVICE_SEARCH_URL = "https://service.dji.com/device/search"
DJI_DEVICE_HOSTS = {"service.dji.com", "account.dji.com"}


@dataclass(frozen=True, slots=True)
class DjiDeviceResult:
    product_name: str
    active_time: str = ""
    image_url: str = ""


def _device_probe_script() -> str:
    """Return a bounded probe that extracts only non-sensitive device fields."""
    return r"""
(() => {
  const text = value => String(value == null ? "" : value).trim();
  const pageText = text(document.body && document.body.innerText).slice(0, 20000);
  const result = {
    host: text(location.host).toLocaleLowerCase(),
    path: text(location.pathname),
    title: text(document.title),
    productName: "",
    activeTime: "",
    imageUrl: "",
    authenticated: false,
    needsLogin: false,
    needsCaptcha: false
  };
  result.needsLogin = result.host === "account.dji.com" ||
    /(?:登录|扫码登录|验证码登录)/.test(pageText.slice(0, 1800));
  result.needsCaptcha = /(?:向右滑动|拖动滑块|滑块验证|完成验证)/.test(pageText);

  const roots = [];
  const addRoot = value => {
    if (value && typeof value === "object") roots.push(value);
  };
  addRoot(window.__INITIAL_STATE__);
  addRoot(window.__NUXT__);
  addRoot(window.__NEXT_DATA__);
  addRoot(window.__APOLLO_STATE__);
  addRoot(window.__STORE__);
  const app = document.querySelector("#app");
  try { addRoot(app && app.__vue__ && app.__vue__.$store && app.__vue__.$store.state); } catch (_) {}
  try { addRoot(app && app.__vue_app__ && app.__vue_app__.config && app.__vue_app__.config.globalProperties && app.__vue_app__.config.globalProperties.$store && app.__vue_app__.config.globalProperties.$store.state); } catch (_) {}

  const queue = roots.map(value => ({ value, depth: 0 }));
  const visited = new Set();
  const usefulKeys = [
    "selfServiceObj", "baseInfo", "deviceInfo", "deviceDetail", "productInfo",
    "productName", "productNameCn", "deviceName", "deviceTypeName", "modelName",
    "productModel", "productType", "activeTime", "activationTime", "activeDate",
    "activationDate", "imageUrl", "productImage", "deviceImage", "productImg",
    "productPic", "picUrl"
  ];
  const pick = (objects, keys) => {
    for (const object of objects) {
      if (!object || typeof object !== "object") continue;
      for (const key of keys) {
        const value = text(object[key]);
        if (value && value !== "[object Object]") return value;
      }
    }
    return "";
  };

  const looksLikeProductName = value => {
    const candidate = text(value);
    if (!candidate || candidate.length < 3 || candidate.length > 100) return false;
    if (/^(?:DJI|大疆)$/.test(candidate)) return false;
    if (/(?:设备信息查询|查询其他设备|服务申请|进度查询|售后服务|登录|注册|序列号|激活时间)/.test(candidate)) return false;
    return /(?:DJI|大疆|Mavic|Air|Mini|Avata|Inspire|Matrice|Phantom|Spark|FPV|Neo|Agriculture)/i.test(candidate);
  };

  let inspected = 0;
  while (queue.length && inspected < 2400 && !result.productName) {
    const current = queue.shift();
    const value = current.value;
    if (!value || typeof value !== "object" || visited.has(value)) continue;
    visited.add(value);
    inspected += 1;
    const nested = [
      value,
      value.selfServiceObj,
      value.baseInfo,
      value.deviceInfo,
      value.deviceDetail,
      value.productInfo
    ].filter(item => item && typeof item === "object");
    const productName = pick(nested, [
      "productName", "productNameCn", "deviceName", "deviceTypeName", "modelName",
      "productModel", "productTitle", "productType"
    ]);
    if (looksLikeProductName(productName) && /\/device\/detail/i.test(result.path)) {
      result.productName = productName;
      result.activeTime = pick(nested, [
        "activeTime", "activationTime", "activeDate", "activationDate"
      ]);
      result.imageUrl = pick(nested, [
        "imageUrl", "productImage", "deviceImage", "productImg", "productPic", "picUrl", "image"
      ]);
      break;
    }
    if (current.depth >= 7) continue;
    for (const key of usefulKeys) {
      const child = value[key];
      if (child && typeof child === "object") {
        queue.push({ value: child, depth: current.depth + 1 });
      }
    }
    if (Array.isArray(value)) {
      for (const child of value.slice(0, 40)) {
        if (child && typeof child === "object") queue.push({ value: child, depth: current.depth + 1 });
      }
    }
    for (const key of Object.keys(value).slice(0, 100)) {
      const child = value[key];
      if (child && typeof child === "object") {
        queue.push({ value: child, depth: current.depth + 1 });
      }
    }
  }

  // DJI has changed its Vue store shape more than once.  The official detail
  // page still renders the product name immediately above the serial-number
  // row, so use the visible text as a safe fallback without returning the SN.
  const lines = pageText.split(/\n+/).map(text).filter(Boolean);
  if (!result.productName && /\/device\/detail/i.test(result.path)) {
    const serialIndex = lines.findIndex(line => /^(?:序列号|Serial(?: Number)?)\s*[：:]/i.test(line));
    if (serialIndex > 0) {
      for (let index = serialIndex - 1; index >= Math.max(0, serialIndex - 6); index -= 1) {
        if (looksLikeProductName(lines[index])) {
          result.productName = lines[index];
          break;
        }
      }
    }
    if (!result.productName) {
      result.productName = lines.find(looksLikeProductName) || "";
    }
  }
  if (!result.activeTime) {
    const activeLine = lines.find(line => /^(?:激活时间|Activation(?: Date| Time)?)\s*[：:]/i.test(line));
    const activeMatch = text(activeLine).match(/(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})/);
    if (activeMatch) result.activeTime = activeMatch[1].replace(/[/.]/g, "-");
  }
  if (!result.imageUrl) {
    const images = Array.from(document.images || []).map(image => ({
      src: text(image.currentSrc || image.src),
      alt: text(image.alt),
      area: Number(image.naturalWidth || image.width || 0) * Number(image.naturalHeight || image.height || 0)
    })).filter(image => image.src && !/(?:logo|avatar|icon)/i.test(image.src));
    images.sort((left, right) => right.area - left.area);
    const matched = images.find(image => result.productName && image.alt.includes(result.productName));
    result.imageUrl = text((matched || images[0] || {}).src);
  }

  const detailHasDevice = /\/device\/detail/i.test(result.path) && (
    Boolean(result.productName) ||
    /(?:序列号|Serial(?: Number)?)\s*[：:]/i.test(pageText) ||
    /(?:激活时间|Activation(?: Date| Time)?)\s*[：:]/i.test(pageText)
  );
  result.authenticated = result.host === "service.dji.com" && detailHasDevice;
  if (result.authenticated) result.needsLogin = false;
  return JSON.stringify(result);
})();
"""


def _decode_probe_payload(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        return data
    if not isinstance(data, str) or not data.strip():
        return None
    try:
        decoded = json.loads(data)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _result_from_probe(data: Any) -> DjiDeviceResult | None:
    payload = _decode_probe_payload(data)
    if payload is None:
        return None
    product_name = str(payload.get("productName") or "").strip()
    if not product_name:
        return None
    return DjiDeviceResult(
        product_name=product_name,
        active_time=str(payload.get("activeTime") or "").strip(),
        image_url=str(payload.get("imageUrl") or "").strip(),
    )


def _login_state_from_probe(data: Any) -> bool | None:
    """Resolve login state while giving authenticated device evidence priority."""
    payload = _decode_probe_payload(data)
    if payload is None:
        return None
    host = str(payload.get("host") or "").strip().lower()
    path = str(payload.get("path") or "").strip().lower()
    if host == "account.dji.com":
        return False
    if bool(payload.get("authenticated")):
        return True
    if host == "service.dji.com" and "/device/detail" in path and str(payload.get("productName") or "").strip():
        return True
    if bool(payload.get("needsLogin")):
        return False
    if host == "service.dji.com":
        return True
    return None


class DjiWebService(QObject):
    """Host DJI's official login/captcha page and read the resolved model only."""

    status_changed = Signal(str, str)
    login_state_changed = Signal(bool, str)
    result_ready = Signal(object)
    query_failed = Signal(str)
    page_ready_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logger = get_logger()
        profile_dir = app_data_dir() / "web-profile" / "dji"
        cache_dir = app_data_dir() / "web-cache" / "dji"
        profile_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        self.profile = QWebEngineProfile("GeGeXD-DJI-Web", self)
        self.profile.setPersistentStoragePath(str(profile_dir))
        self.profile.setCachePath(str(cache_dir))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.page = QWebEnginePage(self.profile, self)
        self.page.urlChanged.connect(self._url_changed)
        self.page.loadFinished.connect(self._load_finished)

        self._query_active = False
        self._query_generation = 0
        self._logged_in = False
        self._login_label = "DJI官网待登录"
        self._probe_inflight = False
        self._shutdown = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(850)
        self._poll_timer.timeout.connect(self._probe)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._timed_out)

    @property
    def query_active(self) -> bool:
        return self._query_active

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def login_label(self) -> str:
        return self._login_label

    def start_query(self, serial: str) -> None:
        serial_value = str(serial or "").strip()
        if not serial_value:
            self.query_failed.emit("请先输入飞行器序列号。")
            return
        self._query_generation += 1
        self._query_active = True
        self._probe_inflight = False
        self._poll_timer.start()
        # Login and the official slider are intentionally user-driven, so allow
        # enough time without silently retrying or bypassing either challenge.
        self._timeout_timer.start(3 * 60 * 1000)
        url = QUrl(DJI_DEVICE_SEARCH_URL)
        query = QUrlQuery()
        query.addQueryItem("lang", "zh-CN")
        query.addQueryItem("re", "cn")
        query.addQueryItem("sn", serial_value)
        url.setQuery(query)
        self.status_changed.emit("正在打开大疆官方查询", "working")
        self.page.load(url)

    def ensure_loaded(self) -> None:
        """Load the official entry once so the persisted login state is visible."""
        if self.page.url().isEmpty():
            self.go_home()
        else:
            QTimer.singleShot(0, self._probe)

    def cancel_query(self) -> None:
        self._query_generation += 1
        self._finish_query()

    def reload(self) -> None:
        if self.page.url().isEmpty():
            self.page.load(QUrl(DJI_DEVICE_SEARCH_URL + "?lang=zh-CN&re=cn"))
        else:
            self.page.triggerAction(QWebEnginePage.WebAction.Reload)

    def go_home(self) -> None:
        self.page.load(QUrl(DJI_DEVICE_SEARCH_URL + "?lang=zh-CN&re=cn"))

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._finish_query()
        delete(self.page)
        delete(self.profile)

    def _finish_query(self) -> None:
        self._query_active = False
        self._probe_inflight = False
        self._poll_timer.stop()
        self._timeout_timer.stop()

    def _url_changed(self, url: QUrl) -> None:
        host = url.host().lower()
        if host == "account.dji.com":
            self._set_login_state(False)
            if self._query_active:
                self.status_changed.emit("请先完成大疆官方登录", "warning")
        elif host == "service.dji.com" and "/device/detail" in url.path():
            self._set_login_state(True)
            if self._query_active:
                self.status_changed.emit("已查到设备，正在读取精准机型", "working")

    def _load_finished(self, ok: bool) -> None:
        self.page_ready_changed.emit(bool(ok))
        if not ok:
            if self._query_active:
                self.status_changed.emit("大疆页面加载失败，可点击刷新重试", "error")
            return
        QTimer.singleShot(250, self._probe)

    def _probe(self) -> None:
        if self._probe_inflight or self._shutdown:
            return
        if self.page.url().host().lower() not in DJI_DEVICE_HOSTS:
            return
        self._probe_inflight = True
        generation = self._query_generation

        def completed(data: Any) -> None:
            if generation != self._query_generation:
                return
            self._probe_inflight = False
            payload = _decode_probe_payload(data)
            login_state = _login_state_from_probe(payload)
            if login_state is not None:
                self._set_login_state(login_state)
            if not self._query_active:
                return
            result = _result_from_probe(payload)
            if result is not None:
                self._finish_query()
                self._set_login_state(True)
                self.logger.info("大疆官方设备机型读取成功 | product_name=%s", result.product_name)
                self.status_changed.emit("大疆精准机型读取成功", "success")
                self.result_ready.emit(result)
                return
            if payload is None:
                return
            if bool(payload.get("needsLogin")):
                self.status_changed.emit("请在左侧大疆官方验证区完成登录", "warning")
            elif bool(payload.get("needsCaptcha")):
                self.status_changed.emit("请在左侧大疆官方验证区手动完成滑块", "warning")
            elif "/device/detail" in str(payload.get("path") or ""):
                self.status_changed.emit("已查到设备，正在读取机型数据", "working")
            else:
                self.status_changed.emit("等待大疆官方查询结果", "working")

        self.page.runJavaScript(_device_probe_script(), completed)

    def _set_login_state(self, logged_in: bool) -> None:
        normalized = bool(logged_in)
        label = "DJI官网已登录" if normalized else "DJI官网待登录"
        if self._logged_in == normalized and self._login_label == label:
            return
        self._logged_in = normalized
        self._login_label = label
        self.login_state_changed.emit(normalized, label)

    def _timed_out(self) -> None:
        if not self._query_active:
            return
        self._finish_query()
        self.query_failed.emit("大疆官方查询超时，请检查登录或滑块后重试。")
