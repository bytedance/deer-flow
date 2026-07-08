"""
Hard-check: validate generated chart HTML has renderable ECharts config.
Run after Agent generates a chart. Auto-detects and reports issues.
Usage: python scripts/validate_chart.py <path/to/chart.html>
Exit code 0 = valid, 1 = invalid (with error details)
"""
import re, sys, os, json, subprocess, tempfile, shutil
from html.parser import HTMLParser


class _HTMLAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.scripts = []
        self._script_attrs = None
        self._script_chunks = []

    def handle_starttag(self, tag, attrs):
        attr_map = {name.lower(): value for name, value in attrs}
        tag = tag.lower()
        self.tags.append((tag, attr_map))
        if tag == "script":
            self._script_attrs = attr_map
            self._script_chunks = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._script_attrs is not None:
            self.scripts.append((self._script_attrs, "".join(self._script_chunks)))
            self._script_attrs = None
            self._script_chunks = []

    def handle_data(self, data):
        if self._script_attrs is not None:
            self._script_chunks.append(data)


def _parse_html(content):
    parser = _HTMLAssetParser()
    parser.feed(content)
    return parser


def _strip_js_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n\r]*", "", text)


def _extract_balanced(text, start_index, opener, closer):
    depth = 0
    in_string = None
    escape = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue
        if char in ("'", '"', "`"):
            in_string = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start_index:index + 1]
    return ""


def _extract_report_chart_specs(content):
    marker = "window.reportChartSpecs"
    marker_index = content.find(marker)
    if marker_index < 0:
        return []
    assignment_index = content.find("=", marker_index)
    if assignment_index < 0:
        return []
    array_start = content.find("[", assignment_index)
    if array_start < 0:
        return []
    raw_array = _extract_balanced(content, array_start, "[", "]")
    if not raw_array:
        return []
    try:
        specs = json.loads(raw_array)
    except json.JSONDecodeError:
        return []
    return specs if isinstance(specs, list) else []


def _is_probably_vendor_script(script):
    vendor_markers = [
        "Apache ECharts",
        "echarts.registerMap",
        "html2canvas",
        "jsPDF",
        "jspdf.umd",
        "sourceMappingURL=jspdf",
        "DOMPurify",
    ]
    if any(marker in script for marker in vendor_markers) and len(script) > 50000:
        return True
    return len(script) > 300000


def _is_echarts_library_script(script):
    return (
        len(script) > 100000
        and "echarts" in script
        and (
            "Apache Software Foundation" in script
            or ".echarts={}" in script
            or "echarts={}" in script
            or "version:\"6." in script
            or "version:'6." in script
            or "version:\"5." in script
            or "version:'5." in script
        )
    )


def _chart_bootstrap_before_echarts(parsed_html):
    first_echarts_library_index = None
    for index, (_, script) in enumerate(parsed_html.scripts):
        if _is_echarts_library_script(script):
            first_echarts_library_index = index
            break
    if first_echarts_library_index is None:
        return False

    for index, (_, script) in enumerate(parsed_html.scripts[:first_echarts_library_index]):
        if (
            "window.dashboardCharts" in script
            or "echarts.init" in script
            or re.search(r"\.setOption\s*\(", script)
        ):
            return True
    return False


def _has_inlined_echarts_library(parsed_html):
    return any(_is_echarts_library_script(script) for _, script in parsed_html.scripts)


def _custom_inline_scripts(parsed_html):
    scripts = []
    for attrs, script in parsed_html.scripts:
        if attrs.get("src"):
            continue
        if not script.strip():
            continue
        if _is_probably_vendor_script(script):
            continue
        scripts.append(script)
    return scripts


def _strip_js_comments(script: str) -> str:
    """Remove JS single-line and multi-line comments, keeping line counts intact."""
    # Remove /* ... */ blocks
    result = re.sub(r"/\*.*?\*/", " ", script, flags=re.DOTALL)
    # Remove // comments (but not URLs like https://)
    result = re.sub(r"(?<!:)//[^\n]*", "", result)
    return result


def _detect_unbalanced_echarts_graphic_calls(scripts):
    errors = []
    pattern = re.compile(r"new\s+echarts\.graphic\.(LinearGradient|RadialGradient)\s*\(")
    for script_index, script in enumerate(scripts, start=1):
        clean = _strip_js_comments(script)
        for match in pattern.finditer(clean):
            call = match.group(1)
            if not _extract_balanced(clean, match.end() - 1, "(", ")"):
                errors.append(
                    f"INVALID JS in custom script #{script_index}: "
                    f"unclosed echarts.graphic.{call}(...) call — "
                    f"close the constructor before closing the option object"
                )
    return errors


def _run_node_syntax_check(scripts):
    node = shutil.which("node")
    if not node:
        return []

    errors = []
    for index, script in enumerate(scripts, start=1):
        wrapped = script
        if "await " in script and "async function" not in script:
            wrapped = f"(async function(){{\n{script}\n}});"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tmp:
            tmp.write(wrapped)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [node, "--check", tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            errors.append(f"JS syntax check failed for custom script #{index}: {exc}")
        else:
            if result.returncode != 0:
                detail = [line for line in (result.stderr or result.stdout).strip().splitlines() if line.strip()]
                useful = [
                    line for line in detail
                    if not line.startswith("Node.js ")
                    and not line.startswith("    at ")
                ]
                syntax_index = next(
                    (i for i, line in enumerate(useful) if "SyntaxError" in line or "Unexpected" in line),
                    None,
                )
                if syntax_index is not None:
                    start = max(0, syntax_index - 3)
                    end = min(len(useful), syntax_index + 2)
                    message = " | ".join(useful[start:end])
                else:
                    message = " | ".join(useful[-5:]) if useful else "unknown syntax error"
                errors.append(f"INVALID JS in custom script #{index}: {message}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return errors


def _unsafe_url(value):
    if value is None:
        return False
    value = value.strip()
    if not value or value.startswith(("#", "data:", "mailto:", "tel:", "javascript:void")):
        return False
    return bool(re.match(r"^(?:https?:)?//|^https?://|^file://", value, re.IGNORECASE))


def _walk_values(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _chart_types_from_specs(specs):
    types = []
    for spec in specs:
        option = spec.get("option") if isinstance(spec, dict) else None
        for value in _walk_values(option):
            if isinstance(value, dict) and isinstance(value.get("type"), str):
                types.append(value["type"])
    return types


def _specs_have_data(specs):
    for spec in specs:
        option = spec.get("option") if isinstance(spec, dict) else None
        for value in _walk_values(option):
            if isinstance(value, dict):
                data = value.get("data")
                source = value.get("source")
                if isinstance(data, list) and len(data) > 0:
                    return True
                if source is not None:
                    return True
    return False


def validate(html_path):
    with open(html_path) as f:
        content = f.read()

    errors = []
    warnings = []
    parsed_html = _parse_html(content)

    # ─────────────────────────────────────────────────────────────
    # 0. Single File Compliance (MUST RUN FIRST — catches most 404s)
    # ─────────────────────────────────────────────────────────────
    # 0a. External script src (not data: URI)
    external_scripts = re.findall(
        r'<script\s[^>]*src\s*=\s*["\'](?!data:)([^"\']+)["\']',
        content, re.IGNORECASE
    )
    if external_scripts:
        for src in external_scripts:
            errors.append(
                f"FORBIDDEN external script: src=\"{src[:120]}\" — "
                f"all JS must be inlined (Single File rule)"
            )

    # 0b. External stylesheet href (not data: URI)
    external_styles = re.findall(
        r'<link\s[^>]*href\s*=\s*["\'](?!data:)([^"\']+)["\']',
        content, re.IGNORECASE
    )
    if external_styles:
        for href in external_styles:
            errors.append(
                f"FORBIDDEN external stylesheet: href=\"{href[:120]}\" — "
                f"all CSS must be inlined (Single File rule)"
            )

    # 0c. Hardcoded localhost IP:port references (the #1 cause of 404 errors)
    hardcoded_urls = re.findall(
        r'(?:https?://)?(?:127\.0\.0\.1|localhost):\d{2,5}[^\s"\'<>]*',
        content
    )
    if hardcoded_urls:
        for url in hardcoded_urls:
            errors.append(
                f"FORBIDDEN hardcoded port URL: \"{url[:120]}\" — "
                f"ports are dynamic, use relative paths or inline everything"
            )

    # 0d. Runtime external loaders also break the Single File rule. These do not
    # appear as literal <script src> tags until the browser executes the page.
    dynamic_external_patterns = [
        (r"\.src\s*=\s*['\"]https?://", "runtime script/style src assignment"),
        (r"fetch\s*\(\s*['\"]https?://", "runtime fetch"),
        (r"innerHTML\s*\+?=\s*['\"][^'\"]*<script[^>]+src\s*=\s*['\"]https?://", "runtime injected script tag"),
    ]
    for pattern, label in dynamic_external_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            errors.append(
                f"FORBIDDEN external loader: {label} — "
                f"all runtime dependencies must be inlined for file:// dashboards"
            )

    # 0e. Invalid global assignment syntax seen in generated dashboards.
    if re.search(r"\bvar\s+window\.", content):
        errors.append(
            "INVALID JS: found `var window.*` — assign globals as `window.name = ...`"
        )

    if _chart_bootstrap_before_echarts(parsed_html):
        errors.append(
            "DASHBOARD: chart bootstrap appears before the inlined ECharts library — "
            "embed ECharts/map/html2canvas/jsPDF/dashboard assets first, then define and run chart bootstrap"
        )

    if "echarts.init" in content and not _has_inlined_echarts_library(parsed_html):
        errors.append(
            "MISSING: inlined ECharts library — generated chart/report/dashboard HTML must embed "
            "assets/echarts/echarts.min.js before any echarts.init call"
        )

    # 0f. Browser-free structural checks. Standalone chart/dashboard files should
    # not contain frames or file/http asset references. These are especially
    # fragile under file:// unique-origin rules.
    for tag, attrs in parsed_html.tags:
        if tag in ("iframe", "frame", "object", "embed"):
            errors.append(
                f"FORBIDDEN embedded frame/object: <{tag}> — "
                f"standalone dashboard HTML must not load itself or nested documents"
            )
        for attr_name in ("src", "href", "data", "poster"):
            attr_value = attrs.get(attr_name)
            if _unsafe_url(attr_value):
                errors.append(
                    f"FORBIDDEN URL asset on <{tag}>: {attr_name}=\"{attr_value[:120]}\" — "
                    f"inline the asset or remove the reference"
                )

    custom_scripts = _custom_inline_scripts(parsed_html)
    errors.extend(_detect_unbalanced_echarts_graphic_calls(custom_scripts))
    errors.extend(_run_node_syntax_check(custom_scripts))

    # ─────────────────────────────────────────────────────────────
    # 1. ECharts init
    # ─────────────────────────────────────────────────────────────
    if "echarts.init" not in content:
        errors.append("MISSING: echarts.init — chart won't render")

    # ─────────────────────────────────────────────────────────────
    # 2. setOption
    # ─────────────────────────────────────────────────────────────
    if "setOption" not in content:
        errors.append("MISSING: setOption — no option applied")

    # ─────────────────────────────────────────────────────────────
    # 3. Unresolved placeholders
    # ─────────────────────────────────────────────────────────────
    unresolved = re.findall(r'\{\{[A-Z_]+\}\}', content)
    if unresolved:
        errors.append(f"UNRESOLVED placeholders: {unresolved}")

    has_report_chart_specs = "window.reportChartSpecs" in content
    report_chart_specs = _extract_report_chart_specs(content)
    stripped_content = _strip_js_comments(content)

    # ─────────────────────────────────────────────────────────────
    # 4. Series type present
    # ─────────────────────────────────────────────────────────────
    if has_report_chart_specs:
        types = _chart_types_from_specs(report_chart_specs)
    else:
        types = re.findall(r"['\"]?type['\"]?\s*:\s*['\"]([^'\"]+)['\"]", stripped_content)
    chart_types = [t for t in types if t in (
        'bar','line','pie','scatter','map','radar','funnel','gauge',
        'heatmap','treemap','sunburst','sankey','graph','tree','boxplot',
        'parallel','candlestick','pictorialBar','themeRiver','chord',
        'lines','effectScatter','bar3D','scatter3D','surface','line3D','custom'
    )]
    if not chart_types:
        errors.append("MISSING: no chart series type found")

    # ─────────────────────────────────────────────────────────────
    # 5. Data present
    # ─────────────────────────────────────────────────────────────
    if has_report_chart_specs:
        has_data = _specs_have_data(report_chart_specs)
    else:
        has_data = re.search(r"['\"]?data['\"]?\s*:\s*\[(?!\])", stripped_content) or \
                   re.search(r"['\"]?source['\"]?\s*:", stripped_content)
    if not has_data:
        errors.append("MISSING: no data in series/dataset")

    # ─────────────────────────────────────────────────────────────
    # 6. 3D charts need echarts-gl
    # ─────────────────────────────────────────────────────────────
    if any(t in ('bar3D','scatter3D','surface','line3D','lines3D') for t in chart_types):
        if "echarts-gl" not in content:
            errors.append("MISSING: echarts-gl not loaded for 3D chart")

    # ─────────────────────────────────────────────────────────────
    # 7. Map/geo charts need GeoJSON
    # ─────────────────────────────────────────────────────────────
    geo_or_map = any(t in ('map','lines','effectScatter') for t in chart_types) or \
                 ('geo' in content and 'coordinateSystem' in content)
    if geo_or_map:
        if "registerMap" not in content and "FeatureCollection" not in content:
            errors.append("MISSING: map GeoJSON not loaded (MAP_INLINE issue?)")

    # ─────────────────────────────────────────────────────────────
    # 8. Dashboard-specific checks
    # ─────────────────────────────────────────────────────────────
    is_dashboard = bool(
        re.search(r'DashboardController|dashboard-container|dashboard-grid', content)
    )
    if is_dashboard:
        # 8a. DashboardController must be defined (dashboard.js inlined)
        if "DashboardController" not in content or "class DashboardController" not in content:
            errors.append(
                "DASHBOARD: DashboardController class not found — "
                "dashboard.js must be inlined in the HTML"
            )

        # 8b. html2canvas must be present for PDF export
        if "html2canvas" not in content:
            errors.append(
                "DASHBOARD: html2canvas not found — "
                "must inline assets/dashboard/html2canvas.min.js for PDF export"
            )

        # 8c. jsPDF must be present for PDF export
        if "jsPDF" not in content:
            errors.append(
                "DASHBOARD: jsPDF not found — "
                "must inline assets/dashboard/jspdf.umd.min.js for PDF export"
            )

        # 8d. Dashboard CSS should be inlined (check for key class names)
        dashboard_css_markers = [
            'dashboard-container', 'dashboard-header', 'dashboard-toolbar',
            'chart-card', 'chart-card-header', 'toast-container'
        ]
        missing_css = [m for m in dashboard_css_markers
                       if f'.{m}' not in content and f'#{m}' not in content
                       and f'class="{m}"' not in content and f"class='{m}'" not in content]
        if len(missing_css) > 3:  # Most markers missing → CSS likely not inlined
            errors.append(
                f"DASHBOARD: dashboard CSS appears missing — "
                f"must inline assets/dashboard/dashboard.css"
            )

        # 8e. downloadChart function must be available
        if "downloadChart" not in content:
            errors.append(
                "DASHBOARD: downloadChart function not found — "
                "chart download buttons will fail"
            )

        # 8f. html2canvas cannot parse several modern CSS color functions.
        # Keep exported dashboards conservative so PDF export works offline.
        unsupported_pdf_css = [
            "color-mix(",
            "oklch(",
            "oklab(",
            "lab(",
            "lch(",
        ]
        found_pdf_css = [token for token in unsupported_pdf_css if token in content]
        if found_pdf_css:
            errors.append(
                f"DASHBOARD: PDF-incompatible CSS color functions found: {found_pdf_css} — "
                f"use hex/rgb/rgba variables so html2canvas PDF export works"
            )

        custom_script_text = "\n".join(custom_scripts)
        runtime_self_load_patterns = [
            (r"document\.location\.href\s*=", "document.location.href assignment"),
            (r"window\.location(?:\.href)?\s*=", "window.location assignment"),
            (r"(?<![\w.])location\.href\s*=", "location.href assignment"),
            (r"window\.open\s*\(", "window.open"),
            (r"createElement\s*\(\s*['\"]iframe['\"]\s*\)", "dynamic iframe creation"),
            (r"\.src\s*=\s*['\"]file://", "runtime file:// src assignment"),
            (r"\.href\s*=\s*['\"]file://", "runtime file:// href assignment"),
        ]
        for pattern, label in runtime_self_load_patterns:
            if re.search(pattern, custom_script_text, re.IGNORECASE):
                errors.append(
                    f"DASHBOARD: forbidden runtime navigation/self-load pattern: {label} — "
                    f"file:// dashboards must not navigate or create nested frames"
                )

        if "async exportDashboard" in content:
            export_match = re.search(
                r"async\s+exportDashboard\s*\([^)]*\)\s*\{",
                content,
            )
            if export_match:
                export_body = _extract_balanced(content, export_match.end() - 1, "{", "}")
                if "try" not in export_body or "catch" not in export_body:
                    errors.append(
                        "DASHBOARD: exportDashboard must catch PDF export errors and fallback to print"
                    )
                if "window.print" not in export_body:
                    errors.append(
                        "DASHBOARD: exportDashboard must include window.print() fallback"
                    )
                if "html2canvas" in export_body and "ignoreElements" not in export_body:
                    errors.append(
                        "DASHBOARD: exportDashboard uses html2canvas without ignoreElements — "
                        "toast/overlay nodes may leak into exported PDF and destabilize export"
                    )
                if (
                    re.search(r"new\s+jsPDF\s*\(", export_body)
                    and "window.jspdf" not in export_body
                    and "jspdf.jsPDF" not in export_body
                ):
                    errors.append(
                        "DASHBOARD: exportDashboard directly calls `new jsPDF(...)` — "
                        "resolve jsPDF via `window.jspdf.jsPDF || window.jsPDF` before creating the PDF"
                    )

    # ─────────────────────────────────────────────────────────────
    # 9. Warnings (non-fatal, but worth noting)
    # ─────────────────────────────────────────────────────────────
    # 9a. File is unusually small (likely missing inline libraries)
    if len(content) < 10000 and "echarts" not in content.lower():
        warnings.append(
            f"WARNING: file is very small ({len(content)} bytes) — "
            f"ECharts library may not be inlined"
        )

    # Report
    if errors or warnings:
        basename = os.path.basename(html_path)
        for w in warnings:
            print(f"⚠️  {basename}: {w}")
        for e in errors:
            print(f"❌ {basename}: {e}")
        if errors:
            return 1
        else:
            return 0  # warnings only = still valid
    else:
        print(f"✅ {os.path.basename(html_path)}: valid chart ({len(content)} bytes, types={chart_types})")
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_chart.py <chart.html>")
        sys.exit(2)
    sys.exit(validate(sys.argv[1]))
