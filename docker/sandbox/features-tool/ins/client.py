import base64
from datetime import datetime
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

try:
    from google.protobuf.json_format import MessageToDict
    from proto import wave_pb2
except Exception:  # pragma: no cover - environment-only fallback
    MessageToDict = None  # type: ignore[assignment]
    wave_pb2 = None  # type: ignore[assignment]

from .spectrum_to_wave import extract_time_domain_wave, get_orbit_points, spectrum_to_wave

from .config import InsSettings


def coerce_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def coerce_type_num(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


_MACHINE_TYPE_TO_SERIES: dict[int, str] = {1: "8k", 4: "2k", 6: "6k", 9: "9k"}

_ENDPOINT_PATH_BY_SERIES: dict[str, str] = {
    "2k": "ins-os-view/data/getTrendDataHis",
    "6k": "ins-os-view/sg6kData/getTrendDataHis",
    "8k": "ins-os-view/sg8kData/getTrendDataHis",
    "9k": "ins-os-view/sg9kData/getTrendDataHis",
}

_TWO_K_NAME_KEY_MAP: dict[str, str] = {
    "速度有效值": "v_rms",
    "加速度峰值": "a_peak",
    "加速度有效值": "a_rms",
    "位移峰峰值": "pp_value",
    "包络谱峰值": "envelope_peak",
    "峭度": "kurtosis",
    "裕度": "margin",
    "脉冲指标": "pulse",
    "波形指标": "wave",
    "当前值": "value",
}

_TWO_K_ALARM_FIELD_MAP: dict[str, tuple[str | None, str | None, str | None]] = {
    "v_rms": ("vRmsBValue", "vRmsCValue", "vRmsDValue"),
    "a_peak": ("aPeakBValue", "aPeakCValue", "aPeakDValue"),
    "a_rms": ("gBValue", "gCValue", "gDValue"),
    "kurtosis": ("kurtosisBValue", "kurtosisCValue", "kurtosisDValue"),
    "margin": ("marginBValue", "marginCValue", None),
    "pulse": ("pulseBValue", "pulseCValue", "pulseDValue"),
    "wave": ("waveBValue", "waveCValue", "waveDValue"),
}


def _resolve_endpoint_series(
    position_type: int | None,
    parent_machine_type: int | None,
) -> str:
    if position_type is not None:
        if 22 <= position_type <= 30:
            return "2k"
        if 61 <= position_type <= 64:
            return "6k"
        if 81 <= position_type <= 83:
            return "8k"
        if 91 <= position_type <= 99:
            return "9k"
    if parent_machine_type is not None:
        return _MACHINE_TYPE_TO_SERIES.get(parent_machine_type, "8k")
    return "8k"


def _extract_2k_alarm_thresholds(
    node: dict[str, Any],
    config_info: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    thresholds: dict[str, dict[str, Any]] = {}
    for feature, (b_key, c_key, d_key) in _TWO_K_ALARM_FIELD_MAP.items():
        tier: dict[str, Any] = {}
        for label, key in (("B", b_key), ("C", c_key), ("D", d_key)):
            if not key:
                continue
            value = config_info.get(key)
            if value is None:
                value = node.get(key)
            if value is not None:
                tier[label] = value
        if tier:
            thresholds[feature] = tier
    return thresholds


def slim_component(
    node: dict[str, Any],
    parent_machine_type: int | None = None,
) -> dict[str, Any]:
    config_info = node.get("configInfo") or {}
    own_type = coerce_type_num(node.get("type"))

    next_parent_type = parent_machine_type
    if own_type in _MACHINE_TYPE_TO_SERIES:
        next_parent_type = own_type

    children = [
        slim_component(child, next_parent_type)
        for child in node.get("children") or []
    ]
    points = [
        slim_component(point, next_parent_type)
        for point in node.get("points") or []
    ]

    result: dict[str, Any] = {
        "id": coerce_id(node.get("id")),
        "name": node.get("name") or "(无名称)",
        "unit_type": node.get("unitType"),
        "type_num": own_type,
    }

    position_type_raw = node.get("positionType")
    if position_type_raw is None:
        position_type_raw = config_info.get("positionType")
    position_type = coerce_type_num(position_type_raw)

    is_point_like = node.get("unitType") == 3 or position_type is not None
    if is_point_like:
        series = _resolve_endpoint_series(position_type, parent_machine_type)
        result["endpoint_series"] = series
        if position_type is not None:
            result["position_type"] = position_type
        if series == "2k":
            thresholds = _extract_2k_alarm_thresholds(node, config_info)
            if thresholds:
                result["alarm_thresholds"] = thresholds
            index_field = node.get("index")
            if index_field is None:
                index_field = config_info.get("index")
            if index_field is not None:
                result["index"] = index_field

    if "h_alarm" in config_info:
        result["h_alarm"] = config_info["h_alarm"]
    if "hh_alarm" in config_info:
        result["hh_alarm"] = config_info["hh_alarm"]
    if "belongShaftId" in config_info:
        result["belongShaftId"] = config_info["belongShaftId"]
    if children:
        result["children"] = children
    if points:
        result["points"] = points
    return result


def normalize_pem(key: str) -> str:
    body = (
        key.replace("-----BEGIN PUBLIC KEY-----", "")
        .replace("-----END PUBLIC KEY-----", "")
        .replace("\n", "")
        .replace("\r", "")
        .replace(" ", "")
    )
    chunks = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(chunks) + "\n-----END PUBLIC KEY-----\n"


def rsa_encrypt(plaintext: str, public_key_pem: str) -> str:
    public_key = serialization.load_pem_public_key(normalize_pem(public_key_pem).encode("utf-8"))
    encrypted = public_key.encrypt(plaintext.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("utf-8")


def _safe_error_detail(response: Any) -> str | None:
    """Extract error detail from a non-2xx response body without raising."""
    try:
        body = response.json()
    except Exception:
        try:
            text = response.text
            return text[:500] if text else None
        except Exception:
            return None
    if isinstance(body, dict):
        return str(body.get("msg") or body.get("message") or body)[:500]
    return str(body)[:500]


class InsApiClient:
    def __init__(self, settings: InsSettings, access_token: str | None = None) -> None:
        self.settings = settings
        self.http = httpx.AsyncClient(
            headers={"Content-Type": "application/json;charset=utf-8"},
            timeout=30.0,
        )
        self.token: str | None = None
        self.access_token = (access_token or settings.access_token or "").strip() or None

    async def close(self) -> None:
        await self.http.aclose()

    async def login(self) -> str:
        encoded_user = rsa_encrypt(self.settings.username, self.settings.rsa_public_key)
        encoded_pass = rsa_encrypt(self.settings.password, self.settings.rsa_public_key)
        response = await self.http.post(
            f"{self.settings.base_url}/ins-os-view/login",
            params={
                "captchaPass": "true",
                "enCodeUser": encoded_user,
                "enCodePassword": encoded_pass,
            },
        )
        response.raise_for_status()
        body = response.json()
        code = body.get("code", 0)
        if code != 200:
            raise RuntimeError(body.get("msg") or "登录失败")

        data = body.get("data") or {}
        token = data.get("token") or body.get("token")
        if not token:
            raise RuntimeError(f"登录响应中缺少 token: {body}")

        self.token = str(token)
        return self.token

    async def ensure_token(self) -> str:
        if self.access_token:
            return self.access_token
        if self.token:
            return self.token
        return await self.login()

    async def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        token = await self.ensure_token()
        response = await self.http.get(
            f"{self.settings.base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        if response.is_error:
            detail = _safe_error_detail(response)
            raise RuntimeError(
                f"InS {response.request.method} {response.request.url} "
                f"→ {response.status_code}{f': {detail}' if detail else ''}"
            )
        body = response.json()
        code = body.get("code", 0)
        if code == 401:
            if self.access_token:
                raise RuntimeError("鉴权失败：Bearer token 无效或已过期")
            self.token = None
            token = await self.login()
            response = await self.http.get(
                f"{self.settings.base_url}/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if response.is_error:
                detail = _safe_error_detail(response)
                raise RuntimeError(
                    f"InS {response.request.method} {response.request.url} "
                    f"→ {response.status_code}{f': {detail}' if detail else ''}"
                )
            body = response.json()
            code = body.get("code", 0)
        if code != 200:
            raise RuntimeError(body.get("msg") or f"请求失败，code={code}")
        return body

    async def get_components(self, device_id: str) -> list[dict[str, Any]]:
        body = await self._get_json(
            "ins-os-manage/organize/getComponentByMachineIds",
            {"operateType": "1", "machineIds": device_id},
        )
        return body.get("data") or []

    async def get_slim_components(self, device_id: str) -> list[dict[str, Any]]:
        components = await self.get_components(device_id)
        return [slim_component(node) for node in components]

    async def get_trend_data(
        self,
        component_id: str,
        start_ms: str,
        end_ms: str,
        features: list[str],
        endpoint_series: str | None = "8k",
        factory_id: str | None = None,
        density: str | int | None = None,
        include_filter: str | None = None,
        type_list: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_component_id = ",".join(
            part.strip() for part in component_id.split(",") if part.strip()
        )
        series = (endpoint_series or "8k").lower()
        path = _ENDPOINT_PATH_BY_SERIES.get(series)
        if path is None:
            raise ValueError(f"Unsupported endpoint_series: {endpoint_series!r}")

        params: dict[str, str] = {
            "gpids": normalized_component_id,
            "startTime": start_ms,
            "endTime": end_ms,
        }

        if series == "8k":
            params["density"] = "high" if density is None else str(density)
            params["includeFilter"] = (
                "history,startstop,blackbox,alarm" if include_filter is None else include_filter
            )
            params["typeList"] = type_list if type_list is not None else ",".join(features)
        elif series == "9k":
            params["density"] = "high" if density is None else str(density)
            params["includeFilter"] = "history" if include_filter is None else include_filter
            params["typeList"] = type_list if type_list is not None else ",".join(features)
        else:
            params["density"] = "1" if density is None else str(density)
            if include_filter is not None:
                params["includeFilter"] = include_filter
            if type_list is not None:
                params["typeList"] = type_list

        if factory_id is not None:
            params["factoryId"] = factory_id

        body = await self._get_json(path, params)

        if series in {"8k", "9k"}:
            return parse_trend_response_multi(body, features)

        rows = _extract_trend_rows(body)
        return parse_trend_response(rows, series)

    async def get_waveform_data(self, component_id: str, time_ms: str) -> dict[str, Any]:
        items = await self._fetch_wave_items(component_id, time_ms)
        if not items:
            raise RuntimeError("未获取到波形数据")
        decoded = items[0]
        sample_rate = float(decoded.get("freq") or 0.0)
        wave_raw = extract_time_domain_wave(decoded)
        wave = [float(v) for v in wave_raw] if wave_raw is not None else []
        spectrum = resolve_spectrum_block(decoded)
        spec_freq = [
            float(index) * sample_rate / max(int(decoded.get("samples") or len(wave) or 1), 1)
            for index in spectrum.get("index", [])
        ]
        spec_amp = [float(v) for v in spectrum.get("amp", [])]
        wave_x = [(i / sample_rate * 1000.0) if sample_rate > 0 else float(i) for i in range(len(wave))]
        return {
            "wave_x": wave_x,
            "wave_y": wave,
            "spec_x": spec_freq,
            "spec_y": spec_amp,
            "sample_rate": sample_rate,
            "speed": float(decoded.get("speed") or 0.0),
            "unit": None,
        }

    async def get_orbit_data(
        self,
        machine_id: str,
        bearing_id: str,
        time_ms: str,
        probe_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_probe_ids = [coerce_id(item) for item in (probe_ids or []) if coerce_id(item)]
        if not normalized_probe_ids:
            components = await self.get_components(machine_id)
            bearing = find_component_by_id(components, bearing_id)
            if not bearing:
                raise RuntimeError(f"未在机组 {machine_id} 的组件树中找到轴承 {bearing_id}")
            normalized_probe_ids = get_shaft_vib_probe_ids(bearing)
        if not normalized_probe_ids:
            raise RuntimeError(
                f"轴承 {bearing_id} 未解析到可用于轴心轨迹的轴振探头，"
                "请检查 device_context.json 中的 bearing_ids / waveform_probe_ids / 挂载关系。"
            )
        items = await self._fetch_wave_items(",".join(normalized_probe_ids), time_ms)
        if not items:
            raise RuntimeError("未获取到轴心轨迹所需波形数据")
        x = items[0]
        y = items[1] if len(items) > 1 else items[0]
        x_wave_raw = extract_time_domain_wave(x)
        y_wave_raw = extract_time_domain_wave(y)
        x_wave = [float(v) for v in x_wave_raw] if x_wave_raw is not None else []
        y_wave = [float(v) for v in y_wave_raw] if y_wave_raw is not None else []
        if not x_wave:
            raise RuntimeError("轴振探头波形为空")
        speed = float(x.get("speed") or 0.0)
        freq = float(x.get("freq") or 0.0)
        samples = int(x.get("samples") or 0)
        points_raw, x_wave, y_wave = get_orbit_points(x_wave, y_wave)
        points = points_raw.tolist() if hasattr(points_raw, "tolist") else points_raw
        points_1x = self._build_orbit_nx_points(x, y, 1, freq, samples, speed)
        points_2x = self._build_orbit_nx_points(x, y, 2, freq, samples, speed)
        return {
            "points": points,
            "points_1x": points_1x,
            "points_2x": points_2x,
            "speed": speed,
            "probe_ids": normalized_probe_ids,
        }

    def _build_orbit_nx_points(
        self,
        x: dict[str, Any],
        y: dict[str, Any],
        n: int,
        freq: float,
        samples: int,
        speed: float,
    ) -> list[list[float]]:
        wx = filter_orbit_nx(x, n, freq, samples, speed)
        wy = filter_orbit_nx(y, n, freq, samples, speed)
        if len(wx) == 0 or len(wy) == 0:
            return []
        per_rev = max(1, round(freq / (speed / 60.0))) if freq > 0 and speed > 0 else len(wx)
        take = min(len(wx), len(wy), per_rev)
        points_raw, _, _ = get_orbit_points(wx[:take], wy[:take])
        return points_raw.tolist() if hasattr(points_raw, "tolist") else points_raw

    async def _fetch_wave_items(self, gpids: str, time_ms: str) -> list[dict[str, Any]]:
        body = await self._get_json(
            "ins-os-view/sg8kData/getWaveDataHis",
            {"gpids": gpids, "timepoint": time_ms},
        )
        data = body.get("data")
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            items = []
        decoded_items: list[dict[str, Any]] = []
        for item in items:
            wave_str = item.get("waveStr") or item.get("wave_str")
            if not isinstance(wave_str, str):
                continue
            clean = "".join(ch for ch in wave_str if not ch.isspace())
            try:
                decoded_items.append(parse_wave_str(clean))
            except Exception:
                continue
        return decoded_items


def datetime_input_to_ms(value: str) -> str:
    if value.isdigit():
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return str(int(datetime.strptime(value, fmt).timestamp() * 1000))
        except ValueError:
            pass
    return value


def find_component_by_id(nodes: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    for node in nodes:
        if coerce_id(node.get("id")) == target_id:
            return node
        children = node.get("children") or []
        found = find_component_by_id(children, target_id)
        if found:
            return found
        points = node.get("points") or []
        found = find_component_by_id(points, target_id)
        if found:
            return found
    return None


def get_shaft_vib_probe_ids(node: dict[str, Any]) -> list[str]:
    probe_ids: list[str] = []

    def walk(current: dict[str, Any]) -> None:
        unit_type = current.get("unitType")
        if unit_type is None:
            unit_type = current.get("unit_type")
        type_num = coerce_type_num(current.get("type"))
        if type_num is None:
            type_num = coerce_type_num(current.get("type_num"))

        if unit_type == 3 and type_num == 83:
            probe_id = coerce_id(current.get("id"))
            if probe_id:
                probe_ids.append(probe_id)

        for key in ("children", "points"):
            for child in current.get(key) or []:
                if isinstance(child, dict):
                    walk(child)

    walk(node)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in probe_ids:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def parse_trend_response_multi(body: dict[str, Any], features: list[str]) -> list[dict[str, Any]]:
    data = body.get("data")
    if data is None:
        return []
    if isinstance(data, dict):
        keys_like_ids = all(
            isinstance(key, str) and isinstance(value, (dict, list)) for key, value in data.items()
        )
        if keys_like_ids and "gpid" not in data and "trendData" not in data:
            items: list[tuple[str | None, Any]] = list(data.items())
        else:
            items = [(None, data)]
    else:
        raw_items = data if isinstance(data, list) else [data]
        items = [(None, item) for item in raw_items]

    point_time_map: dict[tuple[str, str], dict[str, Any]] = {}
    for point_id_hint, item in items:
        if not isinstance(item, dict):
            continue
        point_id = str(item.get("gpid") or item.get("pointId") or item.get("id") or point_id_hint or "")
        series_block = item.get("trendData") or item.get("trend_data") or item.get("data") or item.get("list") or item
        if isinstance(series_block, dict) and isinstance(series_block.get("dataArr"), list):
            entries = series_block["dataArr"]
        elif isinstance(series_block, list):
            entries = series_block
        else:
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ts = extract_time_ms(entry)
            if not ts:
                continue
            slot = point_time_map.setdefault(
                (point_id, ts),
                {
                    "component_id": point_id,
                    "time_ms": ts,
                    "values": {},
                },
            )
            for feature in features:
                value = entry.get(feature)
                if isinstance(value, (int, float)):
                    slot["values"][feature] = float(value)
    results = sorted(point_time_map.values(), key=lambda item: (item["component_id"], item["time_ms"]))
    for item in results:
        item["time"] = format_ms_timestamp(item["time_ms"])
    return results


def extract_time_ms(entry: dict[str, Any]) -> str | None:
    for key in ("time", "ts", "timestamp", "collectTime", "datatime", "collect_time", "timeStamp"):
        raw = entry.get(key)
        if isinstance(raw, (int, float)):
            return str(int(raw))
        if isinstance(raw, str):
            if raw.isdigit():
                return raw
            parsed = datetime_input_to_ms(raw)
            if parsed != raw or raw.isdigit():
                return parsed
    return None


def format_ms_timestamp(value: str) -> str:
    try:
        ms = int(value)
    except ValueError:
        return value
    dt = datetime.fromtimestamp(ms / 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{ms % 1000:03d}"


def parse_wave_str(wave_str: str) -> dict[str, Any]:
    if wave_pb2 is None or MessageToDict is None:
        raise RuntimeError(
            "protobuf or proto.wave_pb2 not available; waveform decoding requires the docker sandbox image"
        )
    wave = wave_pb2.WaveStream()
    wave.ParseFromString(base64.b64decode(wave_str))
    return MessageToDict(wave, preserving_proto_field_name=False)


def filter_orbit_nx(wave_data: dict[str, Any], n: int, freq: float, samples: int, speed: float) -> list[float]:
    spectrum = resolve_spectrum_block(wave_data)
    spec_index = [float(v) for v in spectrum.get("index", [])]
    spec_amp = [float(v) for v in spectrum.get("amp", [])]
    spec_ph = [float(v) for v in spectrum.get("ph", [])]
    if not spec_index or not spec_amp or not spec_ph or samples <= 0 or freq <= 0 or speed <= 0:
        return []
    target_hz = n * speed / 60.0
    nearest = min(
        zip(spec_index, spec_amp, spec_ph),
        key=lambda item: abs((item[0] * freq / max(samples, 1)) - target_hz),
        default=None,
    )
    if nearest is None:
        return []
    index, amp, ph = nearest
    isolated = {
        "waveType": "SPECTRUM",
        "freq": freq,
        "samples": samples,
        "spectrum": {
            "index": [index],
            "amp": [amp],
            "ph": [ph],
        },
    }
    rebuilt = spectrum_to_wave(isolated)
    if rebuilt is None:
        return []
    if hasattr(rebuilt, "tolist"):
        return rebuilt.tolist()
    return list(rebuilt)


def resolve_spectrum_block(wave_data: dict[str, Any]) -> dict[str, Any]:
    spectrum = wave_data.get("spectrum")
    if isinstance(spectrum, dict) and spectrum.get("index"):
        return spectrum
    complex_data = wave_data.get("complex")
    if isinstance(complex_data, dict):
        spectrum = complex_data.get("spectrum")
        if isinstance(spectrum, dict):
            return spectrum
    return {"index": [], "amp": [], "ph": []}


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_trend_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
        # Live 2k/6k payloads wrap the per-sample rows inside the component
        # envelope: ``data=[{gpid, posName, value:[{datatime, value:[...]}, ...]}]``.
        # Detect this shape (``value`` is the sample list, ``datatime`` lives on
        # children) and flatten before handing off to ``parse_trend_response``.
        flattened: list[dict[str, Any]] = []
        for item in items:
            inner = item.get("value")
            if (
                isinstance(inner, list)
                and inner
                and all(
                    isinstance(child, dict) and "datatime" in child and "value" in child
                    for child in inner
                )
            ):
                for child in inner:
                    flattened.append(child)
            elif isinstance(inner, list) and not inner:
                # Empty value array → no data samples for this 2k/6k point.
                pass
            else:
                flattened.append(item)
        return flattened
    if isinstance(data, dict):
        for key in ("dataArr", "list", "trendData", "trend_data", "data"):
            block = data.get(key)
            if isinstance(block, list):
                return [item for item in block if isinstance(item, dict)]
        return [data]
    return []


def parse_trend_response(rows: list[dict[str, Any]], series: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    series = (series or "").lower()
    if series in {"8k", "9k"}:
        return [row for row in rows if isinstance(row, dict)]

    if series not in {"2k", "6k"}:
        return [row for row in rows if isinstance(row, dict)]

    flat_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value_block = row.get("value")
        if not isinstance(value_block, list):
            continue

        flat: dict[str, Any] = {}
        for k in ("datatime", "time", "ts", "timestamp", "collectTime"):
            if k in row:
                flat[k] = row[k]
        for k, v in row.items():
            if k in {"value"}:
                continue
            if k not in flat:
                flat[k] = v

        for entry in value_block:
            if not isinstance(entry, dict):
                continue
            if series == "6k":
                key = entry.get("key")
                if not isinstance(key, str) or not key:
                    continue
            else:
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    continue
                key = _TWO_K_NAME_KEY_MAP.get(name, name)
            flat[key] = _coerce_float(entry.get("value"))

        flat_rows.append(flat)
    return flat_rows
