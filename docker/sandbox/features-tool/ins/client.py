import base64
from datetime import datetime
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from google.protobuf.json_format import MessageToDict

from .spectrum_to_wave import extract_time_domain_wave, get_orbit_points, spectrum_to_wave
from proto import wave_pb2

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


def slim_component(node: dict[str, Any]) -> dict[str, Any]:
    children = [slim_component(child) for child in node.get("children") or []]
    points = [slim_component(point) for point in node.get("points") or []]

    config_info = node.get("configInfo") or {}
    result: dict[str, Any] = {
        "id": coerce_id(node.get("id")),
        "name": node.get("name") or "(无名称)",
        "unit_type": node.get("unitType"),
        "type_num": coerce_type_num(node.get("type")),
    }
    if "h_alarm" in config_info:
        result["h_alarm"] = config_info["h_alarm"]
    if "hh_alarm" in config_info:
        result["hh_alarm"] = config_info["hh_alarm"]
    if "belongShaftId" in config_info:
        result["belongShaftId"]=config_info["belongShaftId"]
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
        response.raise_for_status()
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
            response.raise_for_status()
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
    ) -> list[dict[str, Any]]:
        normalized_component_id = ",".join(
            part.strip() for part in component_id.split(",") if part.strip()
        )
        body = await self._get_json(
            "ins-os-view/sg8kData/getTrendDataHis",
            {
                "gpids": normalized_component_id,
                "startTime": start_ms,
                "endTime": end_ms,
                "density": "high",
                "includeFilter": "history,startstop,blackbox,alarm",
                "typeList": ",".join(features),
            },
        )
        return parse_trend_response_multi(body, features)

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

    async def get_orbit_data(self, machine_id: str, bearing_id: str, time_ms: str) -> dict[str, Any]:
        components = await self.get_components(machine_id)
        bearing = find_component_by_id(components, bearing_id)
        if not bearing:
            raise RuntimeError(f"未在机组 {machine_id} 的组件树中找到轴承 {bearing_id}")
        probe_ids = get_shaft_vib_probe_ids(bearing)
        if not probe_ids:
            probe_ids = [bearing_id]
        items = await self._fetch_wave_items(",".join(probe_ids), time_ms)
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
            "probe_ids": probe_ids,
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
