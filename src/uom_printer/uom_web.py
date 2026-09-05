from __future__ import annotations

import base64
import binascii
import json
import re
import unicodedata
import uuid
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from shiboken6 import delete

from .diagnostics import get_logger
from .paths import app_data_dir
from .registration import RegistrationValidationError, validate_personal_registration_form


UOM_HOME_URL = "https://uom.caac.gov.cn/#/main"
UOM_HOST = "uom.caac.gov.cn"
UOM_ACCOUNT_KEY = "uom-web-default-v1"


_MODEL_BRAND_TOKENS = frozenset({"dji", "大疆", "大疆创新"})


def _model_name_identity(value: Any, *, without_brand: bool = False) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    identity = "".join(character for character in text if character.isalnum())
    if without_brand:
        for token in _MODEL_BRAND_TOKENS:
            identity = identity.replace(token, "")
    return identity


def _model_name_tokens(value: Any) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?|[\u3400-\u9fff]+", text)
    return tuple(token for token in tokens if token not in _MODEL_BRAND_TOKENS)


def _model_name_score(requested_name: str, candidate_name: str) -> float:
    requested = _model_name_identity(requested_name)
    candidate = _model_name_identity(candidate_name)
    if not requested or not candidate:
        return 0.0
    if requested == candidate:
        return 1.0

    requested_core = _model_name_identity(requested_name, without_brand=True) or requested
    candidate_core = _model_name_identity(candidate_name, without_brand=True) or candidate
    if requested_core == candidate_core:
        return 0.995

    score = 0.0
    shorter, longer = sorted((requested_core, candidate_core), key=len)
    if len(shorter) >= 4 and shorter in longer:
        coverage = len(shorter) / max(len(longer), 1)
        score = max(score, 0.86 + 0.12 * coverage)

    sequence_ratio = SequenceMatcher(None, requested_core, candidate_core).ratio()
    score = max(score, 0.48 + 0.46 * sequence_ratio)

    requested_tokens = set(_model_name_tokens(requested_name))
    candidate_tokens = set(_model_name_tokens(candidate_name))
    if requested_tokens and candidate_tokens:
        overlap = requested_tokens & candidate_tokens
        if overlap:
            candidate_coverage = len(overlap) / len(candidate_tokens)
            requested_coverage = len(overlap) / len(requested_tokens)
            token_score = 0.56 + 0.25 * candidate_coverage + 0.17 * requested_coverage
            if len(overlap) == 1 and len(candidate_tokens) > 1:
                token_score -= 0.12
            score = max(score, token_score)
    return min(score, 1.0)


def rank_uom_model_candidates(
    product_name: str,
    models: list[dict[str, Any]],
    *,
    model_code: str = "",
    candidate_limit: int = 8,
    official_product_names: list[str] | None = None,
) -> dict[str, Any]:
    """Choose one safe model or return ranked candidates for user confirmation."""
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_model in models:
        if not isinstance(raw_model, dict) or str(raw_model.get("dataState") or "") == "1":
            continue
        model = dict(raw_model)
        key = (
            str(model.get("id") or "").strip().casefold(),
            _model_name_identity(model.get("chanpxh")),
            _model_name_identity(model.get("chanpmc")),
        )
        if not any(key) or key in seen:
            continue
        seen.add(key)
        deduplicated.append(model)
    if not deduplicated:
        return {"ok": False, "message": "UOM型号库没有返回可用型号。"}

    requested_code = _model_name_identity(model_code)
    if requested_code:
        code_matches = [
            model
            for model in deduplicated
            if _model_name_identity(model.get("chanpxh")) == requested_code
        ]
        if len(code_matches) == 1:
            return {
                "ok": True,
                "ambiguous": False,
                "model": code_matches[0],
                "matchType": "model_code_exact",
            }
        if code_matches:
            return {
                "ok": True,
                "ambiguous": True,
                "candidates": code_matches[:candidate_limit],
                "allModels": deduplicated,
                "matchType": "model_code",
            }

    requested_name = str(product_name or "").strip()
    if not requested_name:
        return {"ok": False, "message": "大疆没有返回可用于匹配的产品名称。"}

    scored = sorted(
        (
            (_model_name_score(requested_name, str(model.get("chanpmc") or "")), model)
            for model in deduplicated
        ),
        key=lambda item: (
            item[0],
            len(_model_name_identity(item[1].get("chanpmc"), without_brand=True)),
        ),
        reverse=True,
    )
    top_score = scored[0][0]
    exact_matches = [model for score, model in scored if score >= 0.995]
    official_name_confirmed = official_product_names is None
    if official_product_names is not None:
        requested_official = _model_name_identity(requested_name, without_brand=True)
        official_name_confirmed = sum(
            1
            for name in official_product_names
            if _model_name_identity(name, without_brand=True) == requested_official
        ) == 1
    if len(exact_matches) == 1 and official_name_confirmed:
        return {
            "ok": True,
            "ambiguous": False,
            "model": exact_matches[0],
            "matchType": "official_catalog_name_exact",
        }
    if exact_matches:
        return {
            "ok": True,
            "ambiguous": True,
            "candidates": exact_matches[:candidate_limit],
            "allModels": deduplicated,
            "matchType": "exact_name" if official_name_confirmed else "unverified_exact_name",
        }

    threshold = max(0.72, top_score - 0.10)
    candidates = [model for score, model in scored if score >= threshold][:candidate_limit]
    if not candidates:
        candidates = [model for _score, model in scored[:candidate_limit]]
    return {
        "ok": True,
        "ambiguous": True,
        "candidates": candidates,
        "allModels": deduplicated,
        "matchType": "similar_name" if top_score >= 0.72 else "manual_fallback",
    }


class UomWebFailure(str):
    """Safe failure text with a machine-readable category for UI recovery."""

    def __new__(
        cls,
        message: str,
        *,
        kind: str = "business",
        outcome_unknown: bool = False,
    ) -> "UomWebFailure":
        value = super().__new__(cls, str(message or "UOM操作失败。"))
        value.kind = str(kind or "business")
        value.outcome_unknown = bool(outcome_unknown)
        return value


def _face_identity_context_error(owner: dict[str, Any]) -> str:
    """Return an error only when the official face-auth context is missing.

    UOM may return display-masked identity fields.  Its official
    ``FaceRecognitionModal`` passes those values back to the UOM face endpoints,
    which resolve the authenticated account server-side.  The desktop client
    must not invent a stricter full-ID requirement or try to restore the value.
    """
    person_name = str(owner.get("xingm") or "").strip()
    certificate_number = str(owner.get("zhengjhm") or "").strip()
    if not person_name or not certificate_number:
        return "人脸认证缺少UOM账号姓名或证件号码。"
    return ""


class UomWebService(QObject):
    """Persistent access to the user's authenticated UOM web session."""

    login_state_changed = Signal(bool, str)
    page_ready_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logger = get_logger()
        profile_dir = app_data_dir() / "web-profile" / "uom"
        cache_dir = app_data_dir() / "web-cache" / "uom"
        profile_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        self.profile = QWebEngineProfile("GeGeXD-UOM-Web", self)
        self.profile.setPersistentStoragePath(str(profile_dir))
        self.profile.setCachePath(str(cache_dir))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profile.setHttpCacheMaximumSize(256 * 1024 * 1024)
        self.profile.setSpellCheckEnabled(False)
        self.page = QWebEnginePage(self.profile, self)
        self.page.urlChanged.connect(self._url_changed)
        self.page.loadStarted.connect(self._load_started)
        self.page.loadFinished.connect(self._load_finished)
        self.page.renderProcessTerminated.connect(self._render_process_terminated)

        self._logged_in = False
        self._login_label = "UOM官网待登录"
        self._request_timers: dict[str, QTimer] = {}
        self._request_deadline_timers: dict[str, QTimer] = {}
        self._request_aborters: dict[str, Callable[[str], None]] = {}
        self._shutdown = False
        self._page_loading = False
        self._last_load_ok: bool | None = None
        self._load_retry_count = 0
        self._login_probe_failures = 0
        self._load_recovery_timer = QTimer(self)
        self._load_recovery_timer.setSingleShot(True)
        self._load_recovery_timer.timeout.connect(self._retry_failed_load)
        self._login_probe = QTimer(self)
        self._login_probe.setInterval(5000)
        self._login_probe.timeout.connect(self._probe_login_state)
        self._login_probe.start()

    @property
    def account_key(self) -> str:
        return UOM_ACCOUNT_KEY

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def login_label(self) -> str:
        return self._login_label

    @property
    def is_page_ready(self) -> bool:
        return self._last_load_ok is True and not self._page_loading

    def ensure_loaded(self) -> None:
        current_url = self.page.url()
        if current_url.isEmpty() or current_url.scheme() not in {"http", "https"}:
            self.page.load(QUrl(UOM_HOME_URL))
        elif self._last_load_ok is False and not self._page_loading:
            self.page.triggerAction(QWebEnginePage.WebAction.Reload)

    def go_home(self) -> None:
        self._load_retry_count = 0
        self._load_recovery_timer.stop()
        self.page.load(QUrl(UOM_HOME_URL))

    def reload(self) -> None:
        self._load_retry_count = 0
        self._load_recovery_timer.stop()
        if self.page.url().isEmpty():
            self.ensure_loaded()
        else:
            self.page.triggerAction(QWebEnginePage.WebAction.Reload)

    def open_registration_page(self) -> None:
        """Open the real-name registration module using the site's own visible menu."""
        script = """
(() => {
  const visible = element => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  const nodes = Array.from(document.querySelectorAll("a,button,[role='menuitem'],li,span"));
  const label = nodes.find(node => (node.textContent || "").trim() === "实名登记" && visible(node));
  if (!label) return false;
  const target = label.closest("a,button,[role='menuitem'],li") || label;
  target.click();
  return true;
})();
"""
        self.page.runJavaScript(script)

    def fetch_personal_registration_context(
        self,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
        provider: str = "wx",
    ) -> None:
        """Load the current owner and start the current official face-verification flow.

        This is an authentication-only gate.  It must not send a serial number,
        aircraft model, registration form or attachment before UOM reports face
        verification success.
        """
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        normalized_provider = str(provider or "wx").strip().lower()
        if normalized_provider not in {"wx", "zfb"}:
            failure("UOM不支持这个人脸认证渠道。")
            return
        provider_js = json.dumps(normalized_provider, ensure_ascii=False)

        body = """
if (!window.nros || !window.nros.http || typeof window.nros.http.get !== "function") {
  throw new Error("UOM runtime unavailable");
}
if (!window.Base64 || typeof window.Base64.encode !== "function") {
  throw new Error("UOM Base64 runtime unavailable");
}

const ageResponse = await window.nros.http.get(
  "/common/getUserAge?rand=" + Math.random()
);
const agePayload = ageResponse && ageResponse.data ? ageResponse.data : ageResponse;
if (!agePayload || Number(agePayload.code) !== 0) {
  return { ok: false, message: "UOM账号年龄校验失败，请刷新官网后重试。" };
}
const age = Number(agePayload.data);
if (Number.isFinite(age) && age < 16) {
  return { ok: false, message: "UOM规则要求实名登记人年满16周岁。" };
}

const ownerResponse = await window.nros.http.get(
  "/uom-uavreg/uomUavRegist/suoyqrData?rand=" + Math.random()
);
const ownerPayload = ownerResponse && ownerResponse.data
  ? ownerResponse.data
  : ownerResponse;
if (!ownerPayload || typeof ownerPayload !== "object") {
  return { ok: false, message: "UOM个人所有人信息读取失败。" };
}

const ownerKeys = [
  "xingm", "zhengjlx", "zhengjhm", "shoujhm", "dianzyx", "uid", "eid"
];
const owner = {};
for (const key of ownerKeys) owner[key] = ownerPayload[key] == null ? "" : ownerPayload[key];
// The official face step only needs the authenticated owner's identity
// context.  Phone, email and registration-form fields are validated later,
// after face verification succeeds and the official registration step opens.
const requiredOwnerKeys = ["xingm", "zhengjlx", "zhengjhm"];
if (requiredOwnerKeys.some(key => !String(owner[key] || "").trim())) {
  return {
    ok: false,
    message: "UOM人脸认证上下文不完整，请刷新官网或重新登录后重试。"
  };
}

const encodeFaceValue = value => window.Base64.encode(
  window.Base64.encode(String(value || ""))
);
const requestedFaceProvider = __FACE_PROVIDER__;
const providerResponse = await window.nros.http.post(
  "/enumData/list",
  { biztype: "EM_NATURAL_TYPE_IN", status: 0 }
);
const providerPayload = providerResponse && providerResponse.data
  ? providerResponse.data
  : providerResponse;
const providerRows = Array.isArray(providerPayload) ? providerPayload : [];
const availableFaceProviders = providerRows
  .filter(item => item && Number(item.status || 0) === 0 && ["wx", "zfb"].includes(String(item.val || "")))
  .map(item => ({
    value: String(item.val || ""),
    title: String(item.title || ""),
    remark: String(item.remark || "")
  }));
if (!availableFaceProviders.length) {
  return { ok: false, message: "UOM当前没有可用的人脸认证渠道。" };
}
const availableValues = availableFaceProviders.map(item => item.value);
const faceProvider = availableValues.includes(requestedFaceProvider)
  ? requestedFaceProvider
  : (availableValues.includes("wx") ? "wx" : availableValues[0]);

const authToken = typeof window.nros.getToken === "function"
  ? String(window.nros.getToken() || "")
  : "";
if (!authToken) {
  return { ok: false, message: "UOM登录令牌已失效，请重新登录后再认证。" };
}
const qrUrl = String(window.osConfig && window.osConfig.baseUrl
  ? window.osConfig.baseUrl
  : window.location.origin) +
  "/wx/getWxaCode?type=" + encodeURIComponent(faceProvider) + "&userName=" +
  encodeURIComponent(encodeFaceValue(owner.xingm)) +
  "&certNo=" + encodeURIComponent(encodeFaceValue(owner.zhengjhm)) +
  "&JTOKENID=" + encodeURIComponent(authToken);
const qrResponse = await fetch(qrUrl, { credentials: "include", cache: "no-store" });
if (!qrResponse.ok) {
  return { ok: false, message: "UOM人脸认证二维码生成失败。" };
}
const detectImageMime = bytes => {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 &&
    bytes[2] === 0x4e && bytes[3] === 0x47 && bytes[4] === 0x0d &&
    bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a
  ) {
    return "image/png";
  }
  if (
    bytes.length >= 6 && bytes[0] === 0x47 && bytes[1] === 0x49 &&
    bytes[2] === 0x46 && bytes[3] === 0x38
  ) {
    return "image/gif";
  }
  if (
    bytes.length >= 12 && bytes[0] === 0x52 && bytes[1] === 0x49 &&
    bytes[2] === 0x46 && bytes[3] === 0x46 && bytes[8] === 0x57 &&
    bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
  ) {
    return "image/webp";
  }
  return "";
};
const bufferToImageDataUrl = async (buffer, hintedType = "") => {
  const bytes = new Uint8Array(buffer);
  const headerType = String(hintedType || "").split(";", 1)[0].trim().toLowerCase();
  const mime = headerType.startsWith("image/") ? headerType : detectImageMime(bytes);
  if (!mime) return "";
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Unable to read UOM face QR image"));
    reader.readAsDataURL(new Blob([buffer], { type: mime }));
  });
};
const qrBuffer = await qrResponse.arrayBuffer();
let faceQrDataUrl = await bufferToImageDataUrl(
  qrBuffer,
  qrResponse.headers.get("content-type") || ""
);

// The current UOM endpoint returns a JPEG without a Content-Type header. Keep
// bounded fallbacks for older deployments that wrap the QR in JSON/base64/URL.
if (!faceQrDataUrl) {
  let responseText = "";
  try {
    responseText = new TextDecoder("utf-8").decode(qrBuffer).trim();
  } catch (_) {}
  let responseValue = responseText;
  try {
    responseValue = JSON.parse(responseText);
  } catch (_) {}
  const candidates = [];
  const collectCandidates = (value, depth = 0) => {
    if (depth > 4 || candidates.length >= 24 || value == null) return;
    if (typeof value === "string") {
      const text = value.trim();
      if (text) candidates.push(text);
      return;
    }
    if (typeof value !== "object") return;
    const preferred = [
      "data", "result", "url", "qrUrl", "qrCode", "qrcode", "image", "base64"
    ];
    for (const key of preferred) {
      if (Object.prototype.hasOwnProperty.call(value, key)) {
        collectCandidates(value[key], depth + 1);
      }
    }
    for (const item of Object.values(value).slice(0, 24)) {
      collectCandidates(item, depth + 1);
    }
  };
  collectCandidates(responseValue);
  const allowedHosts = new Set([window.location.host]);
  try {
    allowedHosts.add(new URL(String(window.osConfig && window.osConfig.baseUrl || "")).host);
  } catch (_) {}
  for (const candidate of candidates) {
    if (candidate.startsWith("data:image/")) {
      faceQrDataUrl = candidate;
      break;
    }
    const rawBase64 = candidate.replace(/^data:[^,]*,/, "").replace(/\\s+/g, "");
    if (rawBase64.length >= 256 && /^[A-Za-z0-9+/]+={0,2}$/.test(rawBase64)) {
      try {
        const binary = atob(rawBase64);
        const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
        const mime = detectImageMime(bytes);
        if (mime) {
          faceQrDataUrl = `data:${mime};base64,${rawBase64}`;
          break;
        }
      } catch (_) {}
    }
    try {
      if (!(
        candidate.startsWith("http://") || candidate.startsWith("https://") || candidate.startsWith("/")
      )) continue;
      const candidateUrl = new URL(candidate, window.location.origin);
      if (!["http:", "https:"].includes(candidateUrl.protocol) || !allowedHosts.has(candidateUrl.host)) {
        continue;
      }
      const imageResponse = await fetch(candidateUrl.href, {
        credentials: "include",
        cache: "no-store"
      });
      if (!imageResponse.ok) continue;
      const imageBuffer = await imageResponse.arrayBuffer();
      faceQrDataUrl = await bufferToImageDataUrl(
        imageBuffer,
        imageResponse.headers.get("content-type") || ""
      );
      if (faceQrDataUrl) break;
    } catch (_) {}
  }
}
if (!faceQrDataUrl.startsWith("data:image/")) {
  return {
    ok: false,
    message: "UOM未返回有效的人脸二维码，请刷新官网或重新登录后重试。"
  };
}
return {
  ok: true,
  owner,
  faceProvider,
  availableFaceProviders,
  faceQrDataUrl
};
"""
        body = body.replace("__FACE_PROVIDER__", provider_js)

        def completed(data: Any) -> None:
            if not isinstance(data, dict):
                failure("UOM实名登记账号信息返回格式异常。")
                return
            if not bool(data.get("ok")):
                failure(str(data.get("message") or "UOM实名登记准备失败。"))
                return
            owner = data.get("owner")
            qr_data = str(data.get("faceQrDataUrl") or "")
            selected_provider = str(data.get("faceProvider") or normalized_provider).strip().lower()
            available_providers = [
                dict(item)
                for item in (data.get("availableFaceProviders") or [])
                if isinstance(item, dict) and str(item.get("value") or "") in {"wx", "zfb"}
            ]
            if not isinstance(owner, dict) or not qr_data.startswith("data:image/"):
                failure("UOM实名登记账号信息返回格式异常。")
                return
            identity_error = _face_identity_context_error(owner)
            if identity_error:
                failure(identity_error)
                return
            success(
                {
                    "owner": dict(owner),
                    "faceProvider": selected_provider,
                    "availableFaceProviders": available_providers,
                    "faceQrDataUrl": qr_data,
                }
            )

        self._run_async_script(body, completed, failure, timeout_ms=35000)

    def poll_face_verification(
        self,
        owner: dict[str, Any],
        provider: str,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        """Poll the official face state once; callers should repeat every five seconds."""
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        owner_data = dict(owner or {})
        identity_error = _face_identity_context_error(owner_data)
        if identity_error:
            failure(identity_error)
            return
        person_name = str(owner_data.get("xingm") or "").strip()
        certificate_number = str(owner_data.get("zhengjhm") or "").strip()
        normalized_provider = str(provider or "wx").strip().lower()
        if normalized_provider not in {"wx", "zfb"}:
            failure("UOM不支持这个人脸认证渠道。")
            return

        requested_js = json.dumps(
            {
                "xingm": person_name,
                "zhengjhm": certificate_number,
                "provider": normalized_provider,
            },
            ensure_ascii=False,
        )
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.post !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
if (!window.Base64 || typeof window.Base64.encode !== "function") {{
  throw new Error("UOM Base64 runtime unavailable");
}}
const requested = {requested_js};
const encodeFaceValue = value => window.Base64.encode(
  window.Base64.encode(String(value || ""))
);
const response = await window.nros.http.post(
  "/home/faceDetectState",
  {{
    userName: encodeFaceValue(requested.xingm),
    certNum: encodeFaceValue(requested.zhengjhm),
    type: requested.provider
  }}
);
const result = response && response.data ? response.data : response;
const code = Number(result && result.code);
return {{
  ok: true,
  completed: code === 4,
  started: code === 1 || code === 2 || code === 3,
  code: Number.isFinite(code) ? code : 0
}};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict) or not bool(data.get("ok")):
                failure("UOM人脸认证状态返回格式异常。")
                return
            success(
                {
                    "completed": bool(data.get("completed")),
                    "started": bool(data.get("started")),
                    "code": int(data.get("code") or 0),
                }
            )

        self._run_async_script(body, completed, failure)

    def poll_wechat_face_verification(
        self,
        owner: dict[str, Any],
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        """Backward-compatible wrapper for the default official WeChat channel."""
        UomWebService.poll_face_verification(self, owner, "wx", success, failure)

    def fetch_official_brand_models(
        self,
        manufacturer_name: str,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        """Read every selectable model for one UOM manufacturer without side effects."""
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        manufacturer = str(manufacturer_name or "").strip()
        if not manufacturer:
            failure("型号库更新缺少生产厂商信息。")
            return

        requested_js = json.dumps({"manufacturerName": manufacturer}, ensure_ascii=False)
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.post !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
const requested = {requested_js};
const normalizeIdentity = value => String(value || "")
  .normalize("NFKC")
  .replace(/\\s+/g, "")
  .toLocaleLowerCase();

const companyResponse = await window.nros.http.post(
  "/uomCompanyInfo/list",
  {{
    pageNum: 1,
    pageSize: 50,
    pagination: true,
    limit: 50,
    offset: 0,
    unitDanwlx: "02",
    unitName: requested.manufacturerName
  }}
);
const companyPayload = companyResponse && companyResponse.data
  ? companyResponse.data
  : companyResponse;
const companies = companyPayload && Array.isArray(companyPayload.rows)
  ? companyPayload.rows
  : [];
const manufacturer = companies.find(row =>
  normalizeIdentity(row.unitName) === normalizeIdentity(requested.manufacturerName)
);
if (!manufacturer || !manufacturer.id) {{
  return {{ ok: false, message: "UOM型号库中没有找到完全一致的生产厂商。" }};
}}

const pageSize = 100;
const maxPages = 20;
const selectable = [];
for (let pageNum = 1; pageNum <= maxPages; pageNum += 1) {{
  const modelResponse = await window.nros.http.post(
    "/uom-uavreg/uomUavModel/listSelect",
    {{
      pageNum,
      pageSize,
      pagination: true,
      limit: pageSize,
      offset: (pageNum - 1) * pageSize,
      shengccsid: String(manufacturer.id)
    }}
  );
  const modelPayload = modelResponse && modelResponse.data ? modelResponse.data : modelResponse;
  const rows = modelPayload && Array.isArray(modelPayload.rows) ? modelPayload.rows : [];
  selectable.push(...rows.filter(row => String(row.dataState || "") !== "1"));
  const total = Number(modelPayload && modelPayload.total || 0);
  if (rows.length === 0 || (total > 0 && selectable.length >= total) || (total <= 0 && rows.length < pageSize)) {{
    break;
  }}
}}
return {{
  ok: true,
  manufacturer: {{
    id: String(manufacturer.id || ""),
    unitName: String(manufacturer.unitName || ""),
    unitUsccode: String(manufacturer.unitUsccode || "")
  }},
  models: selectable.map(row => JSON.parse(JSON.stringify(row)))
}};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict):
                failure("UOM官方型号库返回格式异常。")
                return
            if not bool(data.get("ok")):
                failure(str(data.get("message") or "UOM官方型号库读取失败。"))
                return
            manufacturer = data.get("manufacturer")
            models = data.get("models")
            if not isinstance(manufacturer, dict) or not isinstance(models, list):
                failure("UOM官方型号库返回格式异常。")
                return
            normalized_models = [dict(item) for item in models if isinstance(item, dict)]
            if not normalized_models:
                failure("UOM官方没有返回可用的大疆型号。")
                return
            success({"manufacturer": dict(manufacturer), "models": normalized_models})

        self._run_async_script(body, completed, failure, timeout_ms=45000)

    def fetch_official_brand_model(
        self,
        manufacturer_name: str,
        product_name: str,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
        model_code: str = "",
    ) -> None:
        """Backward-compatible live resolver built on the complete official list."""
        requested_name = str(product_name or "").strip()
        requested_code = str(model_code or "").strip()
        if not requested_name and not requested_code:
            failure("精准匹配缺少产品型号信息。")
            return

        def completed(data: dict[str, Any]) -> None:
            manufacturer = dict(data.get("manufacturer") or {})
            models = [dict(item) for item in data.get("models") or [] if isinstance(item, dict)]
            resolution = rank_uom_model_candidates(
                requested_name,
                models,
                model_code=requested_code,
            )
            if not bool(resolution.get("ok")):
                failure(str(resolution.get("message") or "UOM官方机型匹配失败。"))
                return
            if bool(resolution.get("ambiguous")):
                candidates = resolution.get("candidates")
                if not isinstance(candidates, list):
                    failure("UOM官方候选机型返回格式异常。")
                    return
                normalized_candidates = [dict(item) for item in candidates if isinstance(item, dict)]
                if not normalized_candidates:
                    failure("UOM官方没有返回可供确认的候选型号。")
                    return
                self.logger.info(
                    "UOM官方型号需要人工确认 | candidate_count=%s | match_type=%s | product_name=%s",
                    len(normalized_candidates),
                    str(resolution.get("matchType") or "unknown"),
                    requested_name,
                )
                success(
                    {
                        "ambiguous": True,
                        "manufacturer": dict(manufacturer),
                        "candidates": normalized_candidates,
                        "allModels": [
                            dict(item)
                            for item in resolution.get("allModels") or models
                            if isinstance(item, dict)
                        ],
                        "matchType": str(resolution.get("matchType") or "manual_fallback"),
                    }
                )
                return
            model = resolution.get("model")
            if not isinstance(model, dict):
                failure("UOM官方机型查询返回格式异常。")
                return
            result = {
                "manufacturer": dict(manufacturer),
                "model": dict(model),
                "matchType": str(resolution.get("matchType") or "official_name_exact"),
            }
            self.logger.info(
                "UOM官方机型精准匹配成功 | model_code=%s | product_name=%s",
                str(model.get("chanpxh") or ""),
                str(model.get("chanpmc") or ""),
            )
            success(result)

        UomWebService.fetch_official_brand_models(self, manufacturer_name, completed, failure)

    def upload_registration_photo(
        self,
        image_base64: str,
        filename: str,
        success: Callable[[dict[str, str]], None],
        failure: Callable[[str], None],
    ) -> None:
        """Upload one prepared JPEG to a fresh UOM attachment quote code."""
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        encoded = str(image_base64 or "").strip()
        if encoded.lower().startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        encoded = "".join(encoded.split())
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            failure("待上传照片的Base64数据无效。")
            return
        if not image_bytes or not image_bytes.startswith(b"\xff\xd8\xff"):
            failure("待上传照片不是有效的JPEG图片。")
            return
        if len(image_bytes) > 3 * 1024 * 1024:
            failure("UOM要求单张照片不能超过3MB。")
            return

        safe_filename = str(filename or "").strip().replace("\\", "_").replace("/", "_")
        if not safe_filename:
            safe_filename = "uom-registration.jpg"
        if not safe_filename.lower().endswith((".jpg", ".jpeg")):
            safe_filename += ".jpg"
        encoded_js = json.dumps(base64.b64encode(image_bytes).decode("ascii"))
        filename_js = json.dumps(safe_filename, ensure_ascii=False)
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.get !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
const quoteResponse = await window.nros.http.get(
  "/uomAttachment/quotecode/get?rand=" + Math.random()
);
const quotePayload = quoteResponse && quoteResponse.data
  ? quoteResponse.data
  : quoteResponse;
const quoteCode = String(quotePayload && quotePayload.quotecode || "").trim();
if (!quoteCode) {{
  return {{ ok: false, message: "UOM附件编号获取失败。" }};
}}

const binary = atob({encoded_js});
const bytes = new Uint8Array(binary.length);
for (let index = 0; index < binary.length; index += 1) {{
  bytes[index] = binary.charCodeAt(index);
}}
const file = new File(
  [new Blob([bytes], {{ type: "image/jpeg" }})],
  {filename_js},
  {{ type: "image/jpeg" }}
);
const multipart = new FormData();
multipart.append("file", file);
const baseUrl = String(window.osConfig && window.osConfig.baseUrl
  ? window.osConfig.baseUrl
  : window.location.origin);
const token = typeof window.nros.getToken === "function" ? window.nros.getToken() : "";
const uploadResponse = await fetch(
  baseUrl + "/uomAttachment/upload/" + encodeURIComponent(quoteCode),
  {{
    method: "POST",
    headers: {{ Authorization: token }},
    credentials: "include",
    body: multipart
  }}
);
if (!uploadResponse.ok) {{
  return {{ ok: false, message: "UOM照片上传失败。" }};
}}
let uploadResult = null;
try {{ uploadResult = await uploadResponse.json(); }} catch (_) {{ uploadResult = null; }}
if (uploadResult && uploadResult.code != null && Number(uploadResult.code) !== 0) {{
  return {{
    ok: false,
    message: String(uploadResult.msg || "UOM未接受该照片。")
  }};
}}

const listResponse = await window.nros.http.get(
  "/uomAttachment/list/" + encodeURIComponent(quoteCode) + "?rand=" + Math.random()
);
const listPayload = listResponse && listResponse.data ? listResponse.data : listResponse;
if (!Array.isArray(listPayload) || listPayload.length < 1) {{
  return {{ ok: false, message: "UOM照片上传后未查到附件记录。" }};
}}
return {{
  ok: true,
  quoteCode,
  attachmentId: String(listPayload[0].id || ""),
  fileName: String(listPayload[0].fileName || {filename_js})
}};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict):
                failure("UOM照片上传返回格式异常。")
                return
            if not bool(data.get("ok")):
                failure(str(data.get("message") or "UOM照片上传失败。"))
                return
            quote_code = str(data.get("quoteCode") or "").strip()
            if not quote_code:
                failure("UOM照片上传返回格式异常。")
                return
            success(
                {
                    "quoteCode": quote_code,
                    "attachmentId": str(data.get("attachmentId") or ""),
                    "fileName": str(data.get("fileName") or safe_filename),
                }
            )

        self._run_async_script(body, completed, failure, timeout_ms=60000)

    def submit_personal_registration(
        self,
        confirmed_form: dict[str, Any],
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        """Submit one user-confirmed personal registration through the official API."""
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        try:
            form = validate_personal_registration_form(confirmed_form)
        except RegistrationValidationError as exc:
            failure(str(exc))
            return
        array_fields = ("tongxfs", "bianmfs", "caozfs", "fuzsblx", "shiyyt", "dongllx")
        for key in array_fields:
            value = form.get(key)
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    value = parsed
            if isinstance(value, list):
                form[key] = json.dumps(
                    sorted(str(item) for item in value),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )

        form_js = json.dumps(form, ensure_ascii=False)
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.post !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
const confirmedForm = {form_js};
const submitStartedAt = performance.now();
const submitResponse = await window.nros.http.post(
  "/uom-uavreg/uomUavRegist/add?rand=" + Math.random(),
  confirmedForm
);
const result = submitResponse && submitResponse.data ? submitResponse.data : submitResponse;
if (!result || Number(result.code) !== 0) {{
  return {{
    ok: false,
    message: String(result && result.msg ? result.msg : "UOM未接受本次实名登记。")
  }};
}}
const submitElapsedMs = Math.max(0, Math.round(performance.now() - submitStartedAt));

let productNumberUpdated = true;
let productNumberUpdatePending = false;
const syncStartedAt = performance.now();
const updateOutcome = await Promise.race([
  window.nros.http.post(
    "/uom-uavreg/uomProductNumber/update?productNumber=" +
      encodeURIComponent(String(confirmedForm.chanpxlh || ""))
  ).then(response => ({{ response }})).catch(() => ({{ failed: true }})),
  new Promise(resolve => window.setTimeout(() => resolve({{ pending: true }}), 1500))
]);
if (updateOutcome && updateOutcome.pending) {{
  productNumberUpdatePending = true;
}} else if (updateOutcome && updateOutcome.failed) {{
  productNumberUpdated = false;
}} else {{
  const updateResponse = updateOutcome && updateOutcome.response;
  const updateResult = updateResponse && updateResponse.data
    ? updateResponse.data
    : updateResponse;
  if (updateResult && updateResult.code != null && Number(updateResult.code) !== 0) {{
    productNumberUpdated = false;
  }}
}}
return {{
  ok: true,
  id: String(result.id || ""),
  message: String(result.msg || "注册成功"),
  productNumberUpdated,
  productNumberUpdatePending,
  submitElapsedMs,
  syncElapsedMs: Math.max(0, Math.round(performance.now() - syncStartedAt))
}};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict):
                failure("UOM实名登记返回格式异常。")
                return
            if not bool(data.get("ok")):
                failure(str(data.get("message") or "UOM未接受本次实名登记。"))
                return
            result = {
                "id": str(data.get("id") or ""),
                "message": str(data.get("message") or "注册成功"),
                "productNumberUpdated": bool(data.get("productNumberUpdated", True)),
                "productNumberUpdatePending": bool(data.get("productNumberUpdatePending", False)),
                "submitElapsedMs": max(0, int(data.get("submitElapsedMs") or 0)),
                "syncElapsedMs": max(0, int(data.get("syncElapsedMs") or 0)),
            }
            self.logger.info(
                "UOM实名登记接口提交成功 | product_number_updated=%s | update_pending=%s | submit_ms=%s | sync_ms=%s",
                result["productNumberUpdated"],
                result["productNumberUpdatePending"],
                result["submitElapsedMs"],
                result["syncElapsedMs"],
            )
            success(result)

        self._run_async_script(
            body,
            completed,
            failure,
            timeout_ms=45000,
            side_effect_possible=True,
        )

    def open_cancellation_page(
        self,
        success: Callable[[], None],
        failure: Callable[[str], None],
    ) -> None:
        """Open the official cancellation page without submitting any cancellation action."""
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        cancellation_script = """
(() => {
  const visible = element => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  const labels = new Set(["注销登记", "注销实名登记", "实名注销"]);
  const nodes = Array.from(document.querySelectorAll("a,button,[role='menuitem'],li,span"));
  const label = nodes.find(node => labels.has((node.textContent || "").trim()) && visible(node));
  if (!label) return false;
  const target = label.closest("a,button,[role='menuitem'],li") || label;
  target.click();
  return true;
})();
"""

        def cancellation_clicked(clicked: Any) -> None:
            if bool(clicked):
                success()
                return
            failure("未找到UOM官方注销登记入口，请刷新官网后重试。")

        def registration_menu_clicked(clicked: Any) -> None:
            if not bool(clicked):
                failure("未找到UOM登记管理入口，请确认官网已登录。")
                return
            QTimer.singleShot(
                650,
                lambda: self.page.runJavaScript(cancellation_script, cancellation_clicked),
            )

        def direct_clicked(clicked: Any) -> None:
            if bool(clicked):
                success()
                return
            menu_script = """
(() => {
  const visible = element => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  const nodes = Array.from(document.querySelectorAll("a,button,[role='menuitem'],li,span"));
  const label = nodes.find(node => (node.textContent || "").trim() === "登记管理" && visible(node));
  if (!label) return false;
  const target = label.closest("a,button,[role='menuitem'],li") || label;
  target.click();
  return true;
})();
"""
            self.page.runJavaScript(menu_script, registration_menu_clicked)

        self.page.runJavaScript(cancellation_script, direct_clicked)

    def cancel_registered_aircraft(
        self,
        account_row: dict[str, Any],
        success: Callable[[dict[str, str]], None],
        failure: Callable[[str], None],
    ) -> None:
        """Cancel one active registration owned by the current web account."""
        if self.page.url().host().lower() != UOM_HOST or not self._logged_in:
            failure("请先在右侧UOM官网登录。")
            return

        row = dict(account_row or {})
        registration_id = str(row.get("id") or "").strip()
        uas_code = str(row.get("uasCode") or "").strip()
        product_serial = str(row.get("chanpxlh") or "").strip()
        if not registration_id or not (uas_code or product_serial):
            failure("当前实名记录缺少必要标识，请重新查询后再试。")
            return

        requested_js = json.dumps(
            {
                "id": registration_id,
                "uasCode": uas_code,
                "chanpxlh": product_serial,
                "suoyqrlx": str(row.get("suoyqrlx") or "0").strip() or "0",
            },
            ensure_ascii=False,
        )
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.post !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
const requested = {requested_js};
const normalize = value => String(value == null ? "" : value).trim().toLocaleUpperCase();
const ownerType = String(requested.suoyqrlx || "0") === "1" ? "1" : "0";
let activeRecord = null;
const pageSize = 100;
for (let pageNum = 1; pageNum <= 100; pageNum += 1) {{
  const response = await window.nros.http.post(
    "/uom-uavreg/uomUavRegist/list?rand=" + Math.random(),
    {{
      pageNum,
      pageSize,
      pagination: true,
      limit: pageSize,
      offset: (pageNum - 1) * pageSize,
      suoyqrlx: ownerType,
      params: ownerType,
      zhuangt: "0"
    }}
  );
  const payload = response && response.data ? response.data : response;
  if (!payload || !Array.isArray(payload.rows)) throw new Error("Invalid UOM response");
  activeRecord = payload.rows.find(item =>
    String(item.id || "").trim() === String(requested.id || "").trim() &&
    (!requested.uasCode || normalize(item.uasCode) === normalize(requested.uasCode)) &&
    (!requested.chanpxlh || normalize(item.chanpxlh) === normalize(requested.chanpxlh))
  ) || null;
  if (activeRecord) break;
  const total = Number(payload.total || 0);
  if (payload.rows.length < pageSize || (total > 0 && pageNum * pageSize >= total)) break;
}}
if (!activeRecord) {{
  return {{ ok: false, message: "未在当前账号的有效登记中找到该设备，请重新查询。" }};
}}

const ownerEndpoint = ownerType === "1"
  ? "/uom-uavreg/uomUavRegist/suoyqrDanweiData?rand="
  : "/uom-uavreg/uomUavRegist/suoyqrData?rand=";
const ownerResponse = await window.nros.http.get(ownerEndpoint + Math.random());
const owner = ownerResponse && ownerResponse.data ? ownerResponse.data : ownerResponse;
if (!owner || typeof owner !== "object") {{
  return {{ ok: false, message: "UOM账号所有人信息读取失败，请重新登录后再试。" }};
}}

const form = {{
  uasCode: activeRecord.uasCode,
  shengccsmc: activeRecord.shengccsmc,
  chanpxh: activeRecord.chanpxh,
  chanpmc: activeRecord.chanpmc,
  chanplb: activeRecord.chanplb,
  chanplx: activeRecord.chanplx,
  kongjzl: activeRecord.kongjzl,
  zuidqfzl: activeRecord.zuidqfzl,
  chanpxlh: activeRecord.chanpxlh,
  shimzcid: activeRecord.id,
  numberType: activeRecord.numberType,
  suoyqrlx: ownerType,
  zhuxyy: "3",
  zhuxsm: "所有权变更（出售、转让或赠予等）"
}};
if (ownerType === "1") {{
  Object.assign(form, {{
    danwmc: owner.danwmc,
    usccode: owner.usccode,
    danwlx: owner.danwlx,
    lianxr: owner.lianxr,
    shoujhm: owner.shoujhm,
    uid: owner.uid
  }});
}} else {{
  Object.assign(form, {{
    xingm: owner.xingm,
    zhengjlx: owner.zhengjlx,
    zhengjhm: owner.zhengjhm,
    shoujhm: owner.shoujhm,
    uid: owner.uid,
    eid: owner.eid
  }});
}}

const submitResponse = await window.nros.http.post(
  "/uom-uavreg/uomUavLogout/add?rand=" + Math.random(),
  form
);
const result = submitResponse && submitResponse.data ? submitResponse.data : submitResponse;
if (!result || Number(result.code) !== 0) {{
  return {{
    ok: false,
    message: String(result && result.msg ? result.msg : "UOM未接受本次注销请求。")
  }};
}}
return {{
  ok: true,
  message: String(result.msg || "注销成功"),
  uasCode: String(activeRecord.uasCode || ""),
  chanpxlh: String(activeRecord.chanpxlh || "")
}};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict):
                failure("UOM注销接口返回格式异常。")
                return
            if not bool(data.get("ok")):
                failure(str(data.get("message") or "UOM未接受本次注销请求。"))
                return
            result = {
                "message": str(data.get("message") or "注销成功"),
                "uasCode": str(data.get("uasCode") or uas_code),
                "chanpxlh": str(data.get("chanpxlh") or product_serial),
            }
            self.logger.info("UOM实名注销成功")
            success(result)

        self._run_async_script(
            body,
            completed,
            failure,
            timeout_ms=35000,
            side_effect_possible=True,
        )

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._login_probe.stop()
        self._load_recovery_timer.stop()
        for timer in tuple(self._request_timers.values()):
            timer.stop()
            timer.deleteLater()
        self._request_timers.clear()
        for timer in tuple(self._request_deadline_timers.values()):
            timer.stop()
            timer.deleteLater()
        self._request_deadline_timers.clear()
        self._request_aborters.clear()
        delete(self.page)
        delete(self.profile)

    def _url_changed(self, url: QUrl) -> None:
        if url.host().lower() != UOM_HOST:
            self._set_login_state(False)
        QTimer.singleShot(600, self._probe_login_state)

    def _load_started(self) -> None:
        self._abort_pending_requests("UOM页面已刷新或返回，本次操作已停止，资料已保留，请页面稳定后重试。")
        self._page_loading = True

    def _abort_pending_requests(self, message: str) -> None:
        for abort in tuple(self._request_aborters.values()):
            abort(message)

    def _schedule_load_recovery(self) -> None:
        if self._shutdown or self._load_recovery_timer.isActive() or self._load_retry_count >= 2:
            return
        delays = (1200, 3000)
        delay = delays[min(self._load_retry_count, len(delays) - 1)]
        self._load_retry_count += 1
        self._load_recovery_timer.start(delay)

    def _retry_failed_load(self) -> None:
        if self._shutdown:
            return
        if self._page_loading:
            self._load_recovery_timer.start(700)
            return
        self.logger.info("UOM官网正在进行有界自动恢复 | attempt=%s", self._load_retry_count)
        if self.page.url().isEmpty() or self.page.url().host().lower() != UOM_HOST:
            self.page.load(QUrl(UOM_HOME_URL))
        else:
            self.page.triggerAction(QWebEnginePage.WebAction.Reload)

    def _render_process_terminated(self, status: object, exit_code: int) -> None:
        if self._shutdown:
            return
        normal_status = QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus
        if status == normal_status:
            return
        self._page_loading = False
        self._last_load_ok = False
        self._abort_pending_requests("UOM网页进程异常中断，本次操作已停止，资料已保留，请恢复页面后重试。")
        self.logger.warning(
            "UOM网页渲染进程异常结束 | status=%s | exit_code=%s",
            status,
            exit_code,
        )
        self.page_ready_changed.emit(False)
        self._schedule_load_recovery()

    def _load_finished(self, ok: bool) -> None:
        self._page_loading = False
        self._last_load_ok = bool(ok)
        self.page_ready_changed.emit(ok)
        if not ok:
            self.logger.warning("UOM官网页面加载失败")
            self._schedule_load_recovery()
        else:
            self._load_retry_count = 0
            self._load_recovery_timer.stop()
            self._polish_page_scrollbars()
            QTimer.singleShot(500, self._probe_login_state)

    def _polish_page_scrollbars(self) -> None:
        """Keep the official page scrollable while replacing bulky browser bars."""
        script = """
(() => {
  const styleId = "gegexd-uom-scrollbars";
  let style = document.getElementById(styleId);
  if (!style) {
    style = document.createElement("style");
    style.id = styleId;
    (document.head || document.documentElement).appendChild(style);
  }
  style.textContent = `
    * { scrollbar-width: thin; scrollbar-color: rgba(110,125,145,.38) transparent; }
    *::-webkit-scrollbar { width: 6px; height: 6px; }
    *::-webkit-scrollbar-track { background: transparent; }
    *::-webkit-scrollbar-thumb {
      background: rgba(110,125,145,.32);
      border-radius: 999px;
    }
    *::-webkit-scrollbar-thumb:hover { background: rgba(82,97,115,.58); }
    *::-webkit-scrollbar-button { display: none; width: 0; height: 0; }
  `;
  return true;
})();
"""
        self.page.runJavaScript(script)

    def _set_login_state(self, logged_in: bool) -> None:
        if logged_in:
            self._login_probe_failures = 0
        label = "UOM官网已登录" if logged_in else "UOM官网待登录"
        if logged_in == self._logged_in and label == self._login_label:
            return
        self._logged_in = logged_in
        self._login_label = label
        self.logger.info("UOM网页登录状态变化 | logged_in=%s", logged_in)
        self.login_state_changed.emit(logged_in, label)

    def _probe_login_state(self) -> None:
        if self._shutdown:
            return
        if self.page.url().host().lower() != UOM_HOST:
            self._set_login_state(False)
            return
        if self._page_loading:
            return
        script = """
(() => {
  try {
    if (document.readyState !== "complete") return null;
    if (!window.nros || typeof window.nros.getUser !== "function") return null;
    const user = window.nros.getUser();
    return !!(user && user.id);
  } catch (_) {
    return null;
  }
})();
"""
        self.page.runJavaScript(script, self._login_probe_result)

    def _login_probe_result(self, value: Any) -> None:
        if value is None:
            return
        if bool(value):
            self._set_login_state(True)
            return
        self._login_probe_failures += 1
        if self._login_probe_failures >= 3:
            self._set_login_state(False)

    @staticmethod
    def _transport_failure(status: int, *, side_effect_possible: bool) -> UomWebFailure:
        if int(status or 0) in {401, 403}:
            return UomWebFailure(
                "UOM登录已失效，请重新登录。本次已准备资料仍会保留。",
                kind="session",
            )
        return UomWebFailure(
            "UOM连接暂时中断，本次资料已保留，请稍后再试。",
            kind="unknown" if side_effect_possible else "network",
            outcome_unknown=side_effect_possible,
        )

    def _run_async_script(
        self,
        body: str,
        success: Callable[[Any], None],
        failure: Callable[[str], None],
        timeout_ms: int = 25000,
        *,
        side_effect_possible: bool = False,
    ) -> None:
        if self.page.url().host().lower() != UOM_HOST:
            failure(UomWebFailure("UOM官网尚未打开，请先展开官网并登录。", kind="session"))
            return
        if self._page_loading:
            failure(UomWebFailure("UOM官网仍在加载，本次资料已保留，请稍后再试。", kind="network"))
            return

        token = uuid.uuid4().hex
        token_js = json.dumps(token)
        bootstrap = f"""
(() => {{
  window.__gegexdUomWebBridge = window.__gegexdUomWebBridge || Object.create(null);
  window.__gegexdUomWebBridge[{token_js}] = {{ pending: true }};
  Promise.resolve().then(async () => {{
    const data = await (async () => {{ {body} }})();
    window.__gegexdUomWebBridge[{token_js}] = {{ ok: true, data }};
  }}).catch(error => {{
    const response = error && error.response ? error.response : null;
    const status = Number(response && response.status ? response.status : 0);
    const code = String(error && error.code ? error.code : "").slice(0, 80);
    window.__gegexdUomWebBridge[{token_js}] = {{
      ok: false,
      error: {{ status, code }}
    }};
  }});
  return true;
}})();
"""
        timer = QTimer(self)
        timer.setInterval(160)
        deadline_timer = QTimer(self)
        deadline_timer.setSingleShot(True)
        settled = False

        def cleanup() -> None:
            timer.stop()
            timer.deleteLater()
            deadline_timer.stop()
            deadline_timer.deleteLater()
            self._request_timers.pop(token, None)
            self._request_deadline_timers.pop(token, None)
            self._request_aborters.pop(token, None)

        def fail_request(message: object) -> None:
            nonlocal settled
            if settled:
                return
            settled = True
            cleanup()
            self._probe_login_state()
            if isinstance(message, UomWebFailure):
                failure(message)
                return
            failure(
                UomWebFailure(
                    str(message or "UOM官网响应中断，本次资料已保留，请稍后再试。"),
                    kind="unknown" if side_effect_possible else "network",
                    outcome_unknown=side_effect_possible,
                )
            )

        def abort_request(message: str) -> None:
            fail_request(message)

        def timeout_request() -> None:
            fail_request("UOM官网响应超时，本次资料已保留，请稍后再试。")

        def inspect_result(result: Any) -> None:
            nonlocal settled
            if settled:
                return
            if result in (None, "__PENDING__"):
                return
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = None
            if isinstance(result, dict) and result.get("ok"):
                settled = True
                cleanup()
                self._set_login_state(True)
                success(result.get("data"))
            else:
                error = result.get("error") if isinstance(result, dict) else None
                status = int(error.get("status") or 0) if isinstance(error, dict) else 0
                transport_failure = self._transport_failure(
                    status,
                    side_effect_possible=side_effect_possible,
                )
                if transport_failure.kind == "session":
                    self._set_login_state(False)
                fail_request(transport_failure)

        def poll() -> None:
            if settled:
                return
            probe = f"""
(() => {{
  const value = window.__gegexdUomWebBridge && window.__gegexdUomWebBridge[{token_js}];
  if (!value || value.pending) return "__PENDING__";
  delete window.__gegexdUomWebBridge[{token_js}];
  return JSON.stringify(value);
}})();
"""
            self.page.runJavaScript(probe, inspect_result)

        timer.timeout.connect(poll)
        deadline_timer.timeout.connect(timeout_request)
        self._request_timers[token] = timer
        self._request_deadline_timers[token] = deadline_timer
        self._request_aborters[token] = abort_request
        deadline_timer.start(max(1, int(timeout_ms)))

        def started(_result: Any) -> None:
            if settled:
                return
            timer.start()
            poll()

        self.page.runJavaScript(bootstrap, started)

    def fetch_registered_aircraft(
        self,
        success: Callable[[list[dict[str, Any]]], None],
        failure: Callable[[str], None],
        page_size: int = 100,
    ) -> None:
        """Read only the fields needed to render/identify labels."""
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.post !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
const response = await window.nros.http.post(
  "/uom-uavreg/uomUavRegist/list?rand=" + Math.random(),
  {{
    pageNum: 1,
    pageSize: {max(1, min(int(page_size), 500))},
    pagination: true,
    limit: {max(1, min(int(page_size), 500))},
    offset: 0,
    suoyqrlx: "0",
    params: "0",
    zhuangt: "0"
  }}
);
const payload = response && response.data ? response.data : response;
if (!payload || !Array.isArray(payload.rows)) throw new Error("Invalid UOM response");
const allow = [
  "id", "uasCode", "chanpxlh", "chanpmc", "chanpxh", "shengccsmc",
  "xingm", "danwmc", "suoyqrlx", "shoujhm", "kongjzl", "zuidqfzl",
  "createTime", "zhuangt", "erwm"
];
return {{
  total: Number(payload.total || payload.rows.length),
  rows: payload.rows.map(row => {{
    const result = {{}};
    for (const key of allow) result[key] = row[key] == null ? "" : row[key];
    return result;
  }})
}};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
                failure("UOM实名登记列表返回格式异常。")
                return
            rows = [row for row in data["rows"] if isinstance(row, dict)]
            self.logger.info("UOM实名登记列表读取成功 | rows=%s", len(rows))
            success(rows)

        self._run_async_script(body, completed, failure)

    def search_registered_aircraft(
        self,
        serial: str,
        success: Callable[[list[dict[str, Any]]], None],
        failure: Callable[[str], None],
        page_size: int = 500,
    ) -> None:
        """Search every current-account page for an exact UAS code or product serial."""
        serial_js = json.dumps(str(serial or "").strip())
        size = max(1, min(int(page_size), 500))
        body = f"""
if (!window.nros || !window.nros.http || typeof window.nros.http.post !== "function") {{
  throw new Error("UOM runtime unavailable");
}}
const query = String({serial_js} || "").trim().toLocaleUpperCase();
if (!query) return {{ rows: [] }};
const allow = [
  "id", "uasCode", "chanpxlh", "chanpmc", "chanpxh", "shengccsmc",
  "xingm", "danwmc", "suoyqrlx", "shoujhm", "kongjzl", "zuidqfzl",
  "createTime", "zhuangt", "erwm"
];
const matches = [];
const maxPages = 100;
for (let pageNum = 1; pageNum <= maxPages; pageNum += 1) {{
  const response = await window.nros.http.post(
    "/uom-uavreg/uomUavRegist/list?rand=" + Math.random(),
    {{
      pageNum,
      pageSize: {size},
      pagination: true,
      limit: {size},
      offset: (pageNum - 1) * {size},
      suoyqrlx: "0",
      params: "0",
      zhuangt: "0"
    }}
  );
  const payload = response && response.data ? response.data : response;
  if (!payload || !Array.isArray(payload.rows)) throw new Error("Invalid UOM response");
  for (const row of payload.rows) {{
    const uasCode = String(row.uasCode || "").trim().toLocaleUpperCase();
    const productSerial = String(row.chanpxlh || "").trim().toLocaleUpperCase();
    if (uasCode !== query && productSerial !== query) continue;
    const result = {{}};
    for (const key of allow) result[key] = row[key] == null ? "" : row[key];
    matches.push(result);
  }}
  if (matches.length > 0) break;
  const total = Number(payload.total || 0);
  if (payload.rows.length < {size} || (total > 0 && pageNum * {size} >= total)) break;
}}
return {{ rows: matches }};
"""

        def completed(data: Any) -> None:
            if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
                failure("UOM登录态序列号查询返回格式异常。")
                return
            rows = [row for row in data["rows"] if isinstance(row, dict)]
            self.logger.info("UOM登录态序列号查询成功 | rows=%s", len(rows))
            success(rows)

        self._run_async_script(body, completed, failure)


class WineCompatibleUomWebService(QObject):
    """WebEngine-free service used only while testing the Windows build in Wine."""

    login_state_changed = Signal(bool, str)
    page_ready_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logger = get_logger()
        self.logger.warning("离线界面测试模式：已停用嵌入式UOM网页")

    @property
    def account_key(self) -> str:
        return "uom-wine-compat-v1"

    @property
    def is_logged_in(self) -> bool:
        return False

    @property
    def login_label(self) -> str:
        return "离线界面测试"

    @property
    def is_page_ready(self) -> bool:
        return True

    def ensure_loaded(self) -> None:
        self.page_ready_changed.emit(True)

    def go_home(self) -> None:
        self.page_ready_changed.emit(True)

    def reload(self) -> None:
        self.page_ready_changed.emit(True)

    def open_registration_page(self) -> None:
        self.page_ready_changed.emit(True)

    def fetch_personal_registration_context(
        self,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
        provider: str = "wx",
    ) -> None:
        del success, provider
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中操作实名登记。")

    def poll_face_verification(
        self,
        owner: dict[str, Any],
        provider: str,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        del owner, provider, success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中操作人脸认证。")

    def poll_wechat_face_verification(
        self,
        owner: dict[str, Any],
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        self.poll_face_verification(owner, "wx", success, failure)

    def fetch_official_brand_model(
        self,
        manufacturer_name: str,
        product_name: str,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
        model_code: str = "",
    ) -> None:
        del manufacturer_name, product_name, model_code, success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中查询官方机型。")

    def fetch_official_brand_models(
        self,
        manufacturer_name: str,
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        del manufacturer_name, success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中更新型号库。")

    def upload_registration_photo(
        self,
        image_base64: str,
        filename: str,
        success: Callable[[dict[str, str]], None],
        failure: Callable[[str], None],
    ) -> None:
        del image_base64, filename, success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中上传登记照片。")

    def submit_personal_registration(
        self,
        confirmed_form: dict[str, Any],
        success: Callable[[dict[str, Any]], None],
        failure: Callable[[str], None],
    ) -> None:
        del confirmed_form, success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中提交实名登记。")

    def open_cancellation_page(
        self,
        success: Callable[[], None],
        failure: Callable[[str], None],
    ) -> None:
        del success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中操作注销。")

    def cancel_registered_aircraft(
        self,
        account_row: dict[str, Any],
        success: Callable[[dict[str, str]], None],
        failure: Callable[[str], None],
    ) -> None:
        del account_row, success
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中操作注销。")

    def fetch_registered_aircraft(
        self,
        success: Callable[[list[dict[str, Any]]], None],
        failure: Callable[[str], None],
        page_size: int = 100,
    ) -> None:
        del success, page_size
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中测试官网监听。")

    def search_registered_aircraft(
        self,
        serial: str,
        success: Callable[[list[dict[str, Any]]], None],
        failure: Callable[[str], None],
        page_size: int = 500,
    ) -> None:
        del serial, success, page_size
        failure("离线界面测试模式不加载UOM官网；请在Windows正式版中测试官网查询。")

    def shutdown(self) -> None:
        return
