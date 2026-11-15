"""CICO daily balances email - production version of the approved 2026-10-07 test
(daily_balances_email.py). Triggered by a Slack DM to the bot from Axel, William Filho
or Mariana (hook in app/channels/slack.py -> _handle_cico_trigger).

Flow: pull the newest 'YYMMDD Jeeves - CICO.xlsx' from Axel's OneDrive (FinOps V3/CICO,
top-level only; fetch() tries plain HTTPS with the saved M365 cookies first, then headed Edge
in Brian's desktop session; every download goes to a .part file, is validated as a real xlsx of
the listed size, then renamed - a 0-byte/partial file never lands in the CICO folder) -> render the Bank balances tab exactly as the approved test -> send from
Brian's Gmail to the CICO distribution list -> Slack the trigger user + Brian.

Usage:
  cico_daily_email.py [--send] [--to a@x,b@y] [--file PATH | --no-fetch] [--trigger-user UID] [--force]
Without --send it only writes the HTML preview and prints a summary.
"""
import argparse, base64, datetime as dt, json, os, re, subprocess, sys, time, traceback, zipfile
from pathlib import Path
from urllib.parse import quote

import openpyxl
from openpyxl.styles import fonts
fonts.Font.family.max = 255

SKILLS = os.environ.get("SKILLS_PATH") or r"C:\Jeeves\redshift-bot\deer-flow\skills"
if SKILLS.startswith("/mnt"):
    SKILLS = r"C:\Jeeves\redshift-bot\deer-flow\skills"
sys.path.insert(0, os.path.join(SKILLS, "custom", "_shared"))

ROOT_DF = Path(r"C:\Jeeves\redshift-bot\deer-flow\backend\.deer-flow")
TREAS = ROOT_DF / "treasury"
DL = TREAS / "CICO"
LOG = TREAS / "cico_daily_email.log"
STATE = ROOT_DF / "_cico_email_state.json"
LOCK = TREAS / "cico_daily_email.lock"
M365 = Path(r"C:\Jeeves\redshift-bot\tmp\m365_session.json")
SITE = "https://jeevesorg-my.sharepoint.com/personal/axel_tryjeeves_com"
FOLDER = "/personal/axel_tryjeeves_com/Documents/Documentos/FinOps V3/CICO"
SLACK_TOOL = os.path.join(SKILLS, "custom", "slack-search", "slack_tool.py")
BRIAN_SLACK = "U05B5HGNCN9"

# Distribution = Mariana's '261007 CICO- Daily balances' (2026-10-07 23:04 MT) To-line,
# minus Brian (sender) plus Mariana (she was the sender there).
DIST = [
    "alexander@tryjeeves.com", "dileep@tryjeeves.com", "isabel@tryjeeves.com",
    "shalom@tryjeeves.com", "martha@tryjeeves.com", "lizz@tryjeeves.com",
    "axel@tryjeeves.com", "william.filho@tryjeeves.com", "debbie@tryjeeves.com",
    "pradeepan@tryjeeves.com", "robertoconta@tryjeeves.com",
    "mariana.herreracruz@tryjeeves.com",
]
TRIGGER_NAMES = {"U075NLRHYBX": "Axel", "U0A5AT863BL": "William", "U09AGT85RSN": "Mariana",
                 BRIAN_SLACK: "Brian"}
FILE_RE = re.compile(r"^(\d{6}) Jeeves - CICO(?: v(\d+))?\.xlsx$", re.I)


def say(*a):
    msg = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def slack_thread(channel, ts, text):
    """Reply in the trigger message's thread (bot identity, audited via slack_tool)."""
    args = [sys.executable, SLACK_TOOL, "send", channel, text] + (["--thread", ts] if ts else [])
    try:
        r = subprocess.run(args, timeout=60, capture_output=True, text=True)
        if r.returncode: say("slack thread reply rc", r.returncode, r.stderr[-300:])
    except Exception as e:
        say("slack thread reply failed", channel, e)


def find_trigger(uid):
    """Fallback when the gateway didn't pass --trigger-channel/--trigger-ts: newest CICO-ish
    message from the trigger user in their DM with the bot."""
    try:
        sys.path.insert(0, os.path.dirname(SLACK_TOOL))
        import slack_tool
        bot = slack_tool._get_bot_client()
        ch = bot.conversations_open(users=[uid])["channel"]["id"]
        for m in bot.conversations_history(channel=ch, limit=20).get("messages", []):
            if m.get("user") == uid and re.search(r"cico|balance|saldo", (m.get("text") or "").lower()):
                return ch, m.get("ts")
        return ch, None
    except Exception as e:
        say("find_trigger failed", uid, e)
        return None, None


def completeness(FILE):
    """Rows of the Bank balances tab that had a value on the prior date but are BLANK on the
    current date (unfilled inputs), plus 'Total ...' rows that collapse to zero. 2026-10-16:
    the client-balance inputs (rows 553-568) were left blank, the self-funded block went out
    as $0 vs $15.6M and Alex asked what happened. Rows labelled 'inactive' are ignored (an
    inactive demo Revolut row went blank on 10-15)."""
    wb = openpyxl.load_workbook(FILE, read_only=True, data_only=True)
    grid = [list(r) for r in wb["Bank balances"].iter_rows(min_row=1, max_row=600, values_only=True)]
    wb.close()
    hdr = grid[6]
    date_cols = [i for i, v in enumerate(hdr) if isinstance(v, dt.datetime)]
    def lab(r): return " ".join(str(v).strip() for v in grid[r][:10] if v is not None and str(v).strip())
    summ = next(r for r in range(len(grid)) if "summary by country" in lab(r).lower())
    end = next(r for r in range(summ, len(grid)) if "total cash" in lab(r).lower()) + 1
    def filled(ci): return sum(1 for r in range(8, end) if isinstance(grid[r][ci], (int, float)) and grid[r][ci] != 0)
    dc = [c for c in date_cols if filled(c) > 30]
    cur, prev = dc[-1], dc[-2]
    blanks, zeroed = [], []
    for r in range(8, len(grid)):
        p, v, L = grid[r][prev], grid[r][cur], lab(r)
        if "inactive" in L.lower(): continue
        if isinstance(p, (int, float)) and abs(p) >= 1 and v is None:
            blanks.append((r + 1, L))
        elif (L.lower().startswith("total") and isinstance(p, (int, float)) and abs(p) >= 1000
              and isinstance(v, (int, float)) and abs(v) < 0.5):
            zeroed.append((r + 1, L, p))
    # 2026-11-10: FX tab had no 10-Nov rates -> FX rows (589-597) = 0 -> every non-USD account
    # IFERROR'd to 0 and the email went out at 18.6M (-53.2M d/d). Zeros are not blanks, so the
    # check above missed it. Refuse when any FX rate row is 0/blank on the current date.
    CCYS = {'MXN', 'COP', 'CLP', 'PEN', 'BRL', 'GBP', 'EUR', 'CAD'}
    for r in range(end, len(grid)):
        g = grid[r][6] if len(grid[r]) > 6 else None
        if isinstance(g, str) and g.strip().upper() in CCYS:
            p, v = grid[r][prev], grid[r][cur]
            if isinstance(p, (int, float)) and p > 0 and not (isinstance(v, (int, float)) and v > 0):
                blanks.append((r + 1, f'FX rate {g.strip().upper()} - FX tab has no rate for this date, so every {g.strip().upper()} account converts to 0'))
    return dict(d_cur=hdr[cur], d_prev=hdr[prev], blanks=blanks, zeroed=zeroed)


def slack(uid, text):
    try:
        r = subprocess.run([sys.executable, SLACK_TOOL, "send", uid, text], timeout=60,
                           capture_output=True, text=True)
        if r.returncode: say("slack send rc", r.returncode, r.stderr[-300:])
    except Exception as e:
        say("slack send failed", uid, e)


# ---------------------------------------------------------------- fetch (SharePoint)
class FetchError(RuntimeError):
    pass


MIN_XLSX_BYTES = 1_000_000  # real CICO workbooks are ~31 MB; anything under 1 MB is not one


def _pick(files):
    """Newest 'YYMMDD Jeeves - CICO[ vN].xlsx' from a SharePoint Files listing. Refuses (raises)
    when the newest item is empty/tiny on SharePoint - 2026-10-27 the 261027 item existed as a
    0-byte item from 12:18Z (TimeCreated) until its first content version at 14:30Z, and four
    cron fetches wrote it to disk as a 0-byte xlsx."""
    cands = []
    for f in files:
        m = FILE_RE.match(f["Name"])
        if m: cands.append((m.group(1), int(m.group(2) or 0), f.get("TimeLastModified", ""), f))
    if not cands: raise FetchError("no 'YYMMDD Jeeves - CICO.xlsx' in FinOps V3/CICO")
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    f = cands[-1][3]
    n = int(f.get("Length") or 0)
    if n < MIN_XLSX_BYTES:
        raise FetchError(f"newest CICO file '{f['Name']}' is {n:,} bytes on SharePoint (modified "
                         f"{f.get('TimeLastModified')}) - not a saved workbook yet; not downloaded")
    return f


def _valid_xlsx(path, expected=None):
    """Return None if path is a real xlsx (zip with xl/workbook.xml, size matches listing), else why not."""
    try:
        n = path.stat().st_size
    except OSError as e:
        return f"unreadable ({e})"
    if n < MIN_XLSX_BYTES: return f"{n:,} bytes"
    if expected and n != int(expected): return f"{n:,} bytes but SharePoint lists {int(expected):,}"
    try:
        with zipfile.ZipFile(path) as z:
            if "xl/workbook.xml" not in z.namelist(): return "zip without xl/workbook.xml"
    except zipfile.BadZipFile as e:
        return f"not a zip ({e})"
    return None


def _store(name, expected, write):
    """write(fh) streams the body into DL/<name>.part; validate; atomically rename. Never leaves
    a bad file under the real name (latest_local() would pick it up)."""
    DL.mkdir(parents=True, exist_ok=True)
    dest, part = DL / name, DL / (name + ".part")
    part.unlink(missing_ok=True)
    try:
        with open(part, "wb") as fh:
            write(fh)
        bad = _valid_xlsx(part, expected)
        if bad: raise FetchError(f"downloaded '{name}' is not a valid workbook: {bad}")
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


def fetch_http():
    """Non-browser path: SharePoint REST with the FedAuth/rtFa cookies Edge saved to
    m365_session.json. Works from session 0 (gateway/SYSTEM) - no desktop hop. Raises
    FetchError('auth ...') when the cookies are missing/expired so fetch() can fall back to Edge,
    which re-logs in and refreshes the cookie file."""
    import requests
    if not M365.exists(): raise FetchError("auth: no m365_session.json")
    ses = requests.Session()
    for c in json.loads(M365.read_text(encoding="utf-8")).get("cookies", []):
        if "sharepoint.com" in c.get("domain", ""):
            ses.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    q = quote(FOLDER.replace("'", "''"))
    r = ses.get(SITE + f"/_api/web/GetFolderByServerRelativeUrl('{q}')/Files",
                headers={"Accept": "application/json;odata=nometadata"}, timeout=60, allow_redirects=False)
    if r.status_code in (301, 302, 401, 403) or "json" not in r.headers.get("content-type", ""):
        raise FetchError(f"auth: SharePoint list returned {r.status_code} (cookies expired?)")
    r.raise_for_status()
    f = _pick(r.json().get("value", []))
    fq = quote(f["ServerRelativeUrl"].replace("'", "''"))
    resp = ses.get(SITE + f"/_api/web/GetFileByServerRelativeUrl('{fq}')/$value",
                   timeout=300, stream=True, allow_redirects=False)
    if resp.status_code != 200: raise FetchError(f"download failed {resp.status_code} {f['Name']}")

    def write(fh):
        for ch in resp.iter_content(1 << 20): fh.write(ch)
    dest = _store(f["Name"], f.get("Length"), write)
    say("fetched", f["Name"], "modified", f.get("TimeLastModified"), "via http", f"{dest.stat().st_size:,}B")
    return dest, f.get("TimeLastModified")


def fetch_latest():
    """Headed-Edge path. Must run in an interactive desktop session - call fetch(), which hops
    there from session 0. (2026-10-27 16:50: calling this directly from the agent, which runs in
    session 0, made msedge exit 1002 'Target page, context or browser has been closed'.)"""
    if in_session_zero():
        raise FetchError("fetch_latest() needs a desktop session (Edge cannot start in session 0) - use fetch()")
    sys.path.insert(0, r"C:\Jeeves\redshift-bot\scripts")
    import zscaler_reauth as zr
    zr._load_env_config()
    from playwright.sync_api import sync_playwright

    def login(page):
        page.goto(SITE + "/Documents/Forms/All.aspx", wait_until="domcontentloaded", timeout=60000)
        okta_tries = 0
        for _ in range(40):
            time.sleep(2)
            u = page.url
            if "sharepoint.com" in u and "login" not in u:
                return True
            if "login.microsoftonline.com" in u:
                f = page.locator('input[name="loginfmt"]')
                if f.count() and f.first.is_visible():
                    f.first.fill(zr.OKTA_USERNAME); page.locator("#idSIButton9").first.click(); continue
                k = page.locator("#idSIButton9, #acceptButton")
                if k.count() and k.first.is_visible():
                    k.first.click(); continue
                acct = page.locator('div[data-test-id="' + zr.OKTA_USERNAME + '"], div.table[role="button"]')
                if acct.count() and acct.first.is_visible():
                    acct.first.click(); continue
            if "okta" in u.lower():
                okta_tries += 1
                if okta_tries > 3:
                    break
                fp = page.get_by_text("Sign in with Okta FastPass")
                btn = page.get_by_text("Open Okta Verify", exact=True)
                pw = page.locator('input[type="password"], input[name="credentials.passcode"]')
                body = page.inner_text("body") if page.locator("body").count() else ""
                # 2026-11-12 (after Okta password change): Okta now asks for the password, then a
                # security method, before FastPass. Each step is handled here; then loop again.
                if pw.count() and pw.first.is_visible():
                    pw.first.fill(zr.OKTA_PASSWORD)
                    page.locator('input[type="submit"], button[type="submit"]').first.click()
                    okta_tries -= 1; page.wait_for_timeout(3000); continue
                if "security method" in body:
                    zr._select_mfa_option(page); okta_tries -= 1; continue
                if fp.count() and fp.first.is_visible():
                    fp.first.click()
                    zr._handle_open_okta_verify_button(page)
                elif btn.count():
                    zr._handle_open_okta_verify_button(page)
                else:
                    zr._handle_okta_flow(page)
                try: page.wait_for_url(lambda x: "okta" not in x.lower(), timeout=60000)
                except Exception: pass
        page.screenshot(path=str(TREAS / "cico_email_login_fail.png"))
        return False

    with sync_playwright() as p:
        browser = zr._launch_edge_with_retry(p, args=["--no-first-run", "--no-default-browser-check"])
        kw = {"accept_downloads": True}
        if M365.exists(): kw["storage_state"] = str(M365)
        ctx = browser.new_context(**kw)
        page = ctx.new_page()
        if not login(page):
            browser.close(); raise RuntimeError("SharePoint login failed (see cico_email_login_fail.png)")
        ctx.storage_state(path=str(M365))
        q = quote(FOLDER.replace("'", "''"))
        r = ctx.request.get(SITE + f"/_api/web/GetFolderByServerRelativeUrl('{q}')/Files",
                            headers={"Accept": "application/json;odata=nometadata"}, timeout=60000)
        if not r.ok: raise FetchError(f"list failed {r.status}")
        f = _pick(r.json().get("value", []))
        fq = quote(f["ServerRelativeUrl"].replace("'", "''"))
        resp = ctx.request.get(SITE + f"/_api/web/GetFileByServerRelativeUrl('{fq}')/$value", timeout=300000)
        if not resp.ok: raise FetchError(f"download failed {resp.status} {f['Name']}")
        dest = _store(f["Name"], f.get("Length"), lambda fh: fh.write(resp.body()))
        browser.close()
        say("fetched", f["Name"], "modified", f.get("TimeLastModified"), "via edge")
        return dest, f.get("TimeLastModified")


FETCH_RESULT = TREAS / "cico_fetch_result.json"
REAUTH_DIR = os.path.join(SKILLS, "custom", "zscaler-reauth")


def in_session_zero():
    import ctypes
    sid = ctypes.c_ulong()
    k32 = ctypes.windll.kernel32
    return bool(k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid))) and sid.value == 0


def fetch():
    """1) plain HTTPS with saved cookies (no browser); 2) only if that is an auth failure, headed
    Edge - which cannot start in session 0 (gateway runs as SYSTEM) -> hop to Brian's desktop
    session. A content problem (empty/invalid newest file) raises - Edge would get the same bytes."""
    try:
        return fetch_http()
    except FetchError as e:
        if not str(e).startswith("auth"): raise
        say("http fetch unavailable, falling back to Edge:", e)
    except Exception as e:
        say("http fetch error, falling back to Edge:", repr(e)[:300])
    if not in_session_zero():
        return fetch_latest()
    sys.path.insert(0, REAUTH_DIR)
    from session_launcher import run_in_user_session
    FETCH_RESULT.unlink(missing_ok=True)
    rc, out = run_in_user_session([sys.executable, os.path.abspath(__file__), "--fetch-only"], timeout=600)
    if rc != 0 or not FETCH_RESULT.exists():
        raise RuntimeError(f"SharePoint fetch in user session failed rc={rc}: {str(out)[-300:]}")
    r = json.loads(FETCH_RESULT.read_text(encoding="utf-8"))
    bad = _valid_xlsx(Path(r["path"]))
    if bad: raise FetchError(f"Edge fetch produced an invalid workbook {r['path']}: {bad}")
    return Path(r["path"]), r["modified"]


def latest_local():
    c = [(FILE_RE.match(p.name).group(1), p.stat().st_mtime, p) for p in DL.glob("*.xlsx")
         if FILE_RE.match(p.name) and p.stat().st_size >= MIN_XLSX_BYTES and zipfile.is_zipfile(p)]
    if not c: raise FetchError(f"no valid CICO workbook in {DL}")
    return sorted(c)[-1][2]


# ---------------------------------------------------------------- build (approved logic)
def hidden_rows(path, sheet):
    z = zipfile.ZipFile(path)
    wbx = z.read("xl/workbook.xml").decode("utf8")
    rid = re.search(r'<sheet[^>]*name="%s"[^>]*r:id="([^"]+)"' % re.escape(sheet), wbx).group(1)
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8")
    tgt = re.search(r'Id="%s"[^>]*Target="([^"]+)"' % rid, rels) or re.search(r'Target="([^"]+)"[^>]*Id="%s"' % rid, rels)
    t = tgt.group(1).lstrip("/"); t = t if t.startswith("xl") else "xl/" + t
    hid = set()
    with z.open(t) as f:
        buf = ""
        for chunk in iter(lambda: f.read(1 << 20), b""):
            buf += chunk.decode("utf8", "ignore")
            for m in re.finditer(r"<row [^>]*>", buf):
                tag = m.group(0)
                if 'hidden="1"' in tag or 'hidden="true"' in tag:
                    hid.add(int(re.search(r' r="(\d+)"', tag).group(1)))
            buf = buf[-2000:]
    return hid


_WALLET_RE = re.compile(r'\b(0x[0-9a-fA-F]{30,}|[13][a-km-zA-HJ-NP-Z1-9]{25,40}|T[1-9A-HJ-NP-Za-km-z]{30,40}|bc1[0-9a-z]{25,60}|[1-9A-HJ-NP-Za-km-z]{32,44})\b')

def _mask_wallets(s):
    """Shalom 2026-11-14: mask wallet addresses to their first 10 characters."""
    return _WALLET_RE.sub(lambda m: m.group(0)[:10] + '...', s) if s else s


def build(FILE):
    wb = openpyxl.load_workbook(FILE, read_only=True, data_only=True)
    ws = wb["Bank balances"]
    grid = [list(r) for r in ws.iter_rows(min_row=1, max_row=600, values_only=True)]
    hdr = grid[6]

    def find(label):
        for i, v in enumerate(hdr):
            if isinstance(v, str) and v.strip().lower().startswith(label): return i
    ci_country, ci_bank, ci_acct, ci_ccy = find("country"), find("bank"), find("account"), find("original")
    date_cols = [i for i, v in enumerate(hdr) if isinstance(v, dt.datetime)]
    start = 8
    def rowtxt(r): return " ".join(str(v) for v in grid[r][:10] if v is not None).lower()
    summ = next(r for r in range(len(grid)) if "summary by country" in rowtxt(r))
    end = next(r for r in range(summ, len(grid)) if "total cash" in rowtxt(r)) + 1
    HIDDEN = hidden_rows(FILE, "Bank balances")
    cim = next(r for r in range(start, end) if any(k in rowtxt(r) for k in ("cim reporting", "summary by currency")))  # renamed in 261030
    nb = next(r for r in range(len(grid)) if "nb controlled accounts" in rowtxt(r))
    nb_end = next(r for r in range(nb, len(grid)) if "total cash" in rowtxt(r))
    ORDER = list(range(start, cim)) + list(range(nb, nb_end + 1)) + list(range(summ, end))
    RENAME = {nb: "NB Liquidity", nb_end: "Total NB Liquidity"}

    def filled(ci):
        return sum(1 for r in range(start, end) if isinstance(grid[r][ci], (int, float)) and grid[r][ci] != 0)
    dc = [c for c in date_cols if filled(c) > 30]
    cur, prev = dc[-1], dc[-2]
    d_cur, d_prev = hdr[cur], hdr[prev]

    def fmt(v):
        if not isinstance(v, (int, float)) or abs(v) < 0.5: return "-"
        s = f"{abs(v):,.0f}"
        return f"({s})" if v < 0 else s

    rows_html, big_moves = [], []
    for r in ORDER:
        if (r + 1) in HIDDEN and r not in RENAME: continue
        row = grid[r]
        labels = [row[ci_country], row[ci_bank], row[ci_acct], row[ci_ccy]]
        v, p = row[cur], row[prev]
        txt = [str(x).strip() if x is not None else "" for x in labels]
        if nb < r < nb_end and not any(txt):
            t2 = [str(x).strip() for x in row[:ci_ccy + 3] if isinstance(x, str) and x.strip()]
            txt = (t2 + ["", "", "", ""])[:4]
        # 2026-11-14 (Shalom): never print full crypto wallet addresses - show first 10 chars only.
        txt = [_mask_wallets(x) for x in txt]
        section = next((str(x) for x in row[:ci_country + 1] if isinstance(x, str) and x.strip() and x.strip() != "x"), "")
        if r in RENAME: section, txt = RENAME[r], ['', '', '', '']
        if not any(txt) and not section: continue
        if not any(txt):
            is_total = isinstance(v, (int, float))
            style = "font-weight:bold;background:#f2f2f2" if is_total else "font-weight:bold;padding-top:10px"
            delta = (v - p) if isinstance(v, (int, float)) and isinstance(p, (int, float)) else None
            rows_html.append(f'<tr style="{style}"><td colspan="4">{section}</td><td align="right">{fmt(v) if is_total else ""}</td>'
                             f'<td align="right">{fmt(delta) if delta is not None else ""}</td></tr>')
            continue
        if not isinstance(v, (int, float)) and not isinstance(p, (int, float)): continue
        delta = (v or 0) - (p or 0) if isinstance(v, (int, float)) else None
        flag = ' style="color:#b00000"' if delta is not None and abs(delta) >= 1_000_000 else ""
        if flag: big_moves.append(f"{txt[1]} {txt[2]} {fmt(delta)}")
        rows_html.append("<tr>" + "".join(f"<td>{t}</td>" for t in txt) +
                         f'<td align="right">{fmt(v)}</td><td align="right"{flag}>{fmt(delta)}</td></tr>')

    total_v, total_p = grid[end - 1][cur], grid[end - 1][prev]
    html = f"""<div style="font-family:Calibri,Arial;font-size:12px">
<p><b>Bank balances &ndash; {d_cur:%d-%b-%y}</b> (USD; &Delta; vs {d_prev:%d-%b-%y}; moves &ge; $1M in red)</p>
<table cellspacing="0" cellpadding="3" style="border-collapse:collapse;font-size:12px">
<tr style="background:#1f3864;color:white"><th align="left">Country</th><th align="left">Bank / platform</th>
<th align="left">Account</th><th align="left">Ccy</th><th align="right">{d_cur:%d-%b-%y}</th><th align="right">&Delta; d/d</th></tr>
{''.join(rows_html)}
</table>
<p style="color:#888">NB Liquidity = CICO &lsquo;NB controlled accounts&rsquo; block (BTG 6540 and JPM 9269 at 80%), as Axel built it. Generated from {os.path.basename(FILE)} (Bank balances tab).</p></div>"""
    return dict(html=html, d_cur=d_cur, d_prev=d_prev, rows=len(rows_html), total=total_v,
                total_delta=(total_v - total_p) if isinstance(total_v, (int, float)) and isinstance(total_p, (int, float)) else None,
                big_moves=big_moves)


WB_CASH_STATE = ROOT_DF / "_cico_workbook_state.json"


def write_cash_state(FILE):
    """Summary totals straight from the CICO workbook (same file the daily email is built
    from) -> _cico_workbook_state.json. cm_morning_brief prefers this over the OCR'd
    _cico_state.json whenever its balance date is newer (2026-10-12: brief showed the
    10/07 screenshot as '5 days stale' while the bot itself had sent the 10/09 email)."""
    wb = openpyxl.load_workbook(FILE, read_only=True, data_only=True)
    ws = wb["Bank balances"]
    grid = [list(r) for r in ws.iter_rows(min_row=1, max_row=600, values_only=True)]
    hdr = grid[6]
    date_cols = [i for i, v in enumerate(hdr) if isinstance(v, dt.datetime)]
    def has(r, txt):
        return any(isinstance(x, str) and txt in x.lower() for x in grid[r][:10])
    summ = next(r for r in range(len(grid)) if has(r, "summary by country"))
    def filled(ci):
        return sum(1 for r in range(8, summ) if isinstance(grid[r][ci], (int, float)) and grid[r][ci] != 0)
    cur = [c for c in date_cols if filled(c) > 30][-1]
    def val(label, after=0):
        for r in range(after, len(grid)):
            labs = [x.strip().lower() for x in grid[r][:10] if isinstance(x, str)]
            if label in labs:
                v = grid[r][cur]
                return round(v, 2) if isinstance(v, (int, float)) else None
        return None
    nb_hdr = next(r for r in range(len(grid)) if has(r, "nb controlled accounts"))
    d_cur = hdr[cur]
    st = {
        "source": "cico_workbook",
        "source_file": FILE.name,
        "as_of": f"{d_cur:%Y-%m-%d}",
        "source_date": f"{d_cur:%a, %d %b %Y} 00:00:00 -0600",
        "extracted_at": dt.datetime.now().isoformat(),
        "total_cash_usd": val("total cash"),
        "daca_pledged_usd": val("daca + pledged countries"),
        "prepaid_daca_pledged_usd": val("prepaid daca + pledged countries"),
        "restricted_deposits_usd": val("total restricted deposits accounts balance"),
        "total_cash_plus_restricted_usd": val("total cash + restricted deposits"),
        "nb_liquidity_usd": val("total cash", nb_hdr),
    }
    WB_CASH_STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return st


def send_mail(html, subject, to):
    from email.mime.text import MIMEText
    from google_auth import get_credentials
    from googleapiclient.discovery import build as gbuild
    m = MIMEText(html, "html"); m["to"] = ", ".join(to); m["subject"] = subject
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "_shared"))
    from outbound_policy import assert_internal_emails
    assert_internal_emails(to, "cico_daily_email")  # outbound policy 2026-11-02: internal-only auto-send
    svc = gbuild("gmail", "v1", credentials=get_credentials())
    return svc.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute().get("id")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true"); ap.add_argument("--to")
    ap.add_argument("--file"); ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--trigger-user"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--correction", action="store_true")  # resend with 'CORRECTED: ' subject (implies --force)
    ap.add_argument("--trigger-channel"); ap.add_argument("--trigger-ts")
    a = ap.parse_args()
    if a.fetch_only:
        pth, mod = fetch_latest()
        FETCH_RESULT.write_text(json.dumps({"path": str(pth), "modified": mod}), encoding="utf-8")
        return
    who = TRIGGER_NAMES.get(a.trigger_user or "", a.trigger_user or "manual")

    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 900:
        say("already running - lock held")
        if a.trigger_user: slack(a.trigger_user, "The CICO email is already being generated - confirmation coming shortly.")
        return
    LOCK.write_text(str(os.getpid()))
    try:
        if a.file: FILE, mod = Path(a.file), None
        elif a.no_fetch: FILE, mod = latest_local(), None
        else: FILE, mod = fetch()
        b = build(FILE)
        try:
            write_cash_state(FILE)
        except Exception as e:
            say("cash-state write failed (email unaffected):", repr(e))
        key = f"{b['d_cur']:%Y-%m-%d}"
        subject = ("CORRECTED: " if a.correction else "") + f"{b['d_cur']:%y%m%d} CICO - Daily balances"
        if a.correction: a.force = True
        (TREAS / "cico_daily_email_preview.html").write_text(b["html"], encoding="utf-8")
        tot = f"${b['total']:,.0f}" if isinstance(b["total"], (int, float)) else "n/a"
        dlt = (f" ({'+' if b['total_delta'] >= 0 else '-'}${abs(b['total_delta']):,.0f} d/d)"
               if b["total_delta"] is not None else "")
        say("built", FILE.name, "date", key, "prev", f"{b['d_prev']:%Y-%m-%d}", "rows", b["rows"], "total", tot, dlt)
        cp = completeness(FILE)
        if cp["blanks"] or cp["zeroed"]:
            say("INCOMPLETE", FILE.name, "blank rows", [x[0] for x in cp["blanks"]], "zeroed totals", [x[0] for x in cp["zeroed"]])
            if a.send:
                # Refuse to send. Reply ONLY in the trigger message's thread - no DM to Brian.
                items = [f"- row {r}: {L[:110]}" for r, L in cp["blanks"][:15]]
                if len(cp["blanks"]) > 15: items.append(f"- ...and {len(cp['blanks']) - 15} more")
                items += [f"- row {r}: {L[:60]} shows 0 (was {p:,.0f} on {cp['d_prev']:%d-%b})" for r, L, p in cp["zeroed"]]
                hi = f"Hi {who} - " if who not in ("manual", "Brian") else ""
                msg = (f"{hi}I haven't sent the {cp['d_cur']:%d-%b} CICO email: {FILE.name} isn't complete. "
                       f"These rows on the Bank balances tab are blank for {cp['d_cur']:%d-%b} but had values on "
                       f"{cp['d_prev']:%d-%b}, so the email would show them as zero:\n" + "\n".join(items) +
                       "\nFill them in, save the file, and message me *CICO* again - I'll send it once it's complete.")
                if a.trigger_user:
                    ch, ts = (a.trigger_channel, a.trigger_ts) if a.trigger_channel else find_trigger(a.trigger_user)
                    if ch: slack_thread(ch, ts, msg)
                    else: say("could not resolve trigger message - no reply posted")
                else:
                    print(msg)
                return
        if not a.send: return

        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"sent": {}}
        prior = st["sent"].get(key)
        if prior and not a.force and not a.to:
            msg = (f"'{subject}' already went out at {prior['at']} (triggered by {prior['by']}), and the latest "
                   f"filled date in {FILE.name} is still {b['d_cur']:%d-%b}. If today's balances aren't in the CICO yet, "
                   f"update it and message me again. To re-send the same date, message 'CICO resend'.")
            if a.trigger_user: slack(a.trigger_user, msg)
            say("skip - already sent", key); return
        to = a.to.split(",") if a.to else DIST
        mid = send_mail(b["html"], subject, to)
        if not a.to:
            st["sent"][key] = {"at": time.strftime("%Y-%m-%d %H:%M"), "by": who, "file": FILE.name,
                               "file_modified": mod, "msg_id": mid, "total": b["total"], "to": to}
            STATE.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
        say("sent", subject, "to", len(to), "id", mid)
        moves = ("; $1M+ moves: " + ", ".join(b["big_moves"][:6])) if b["big_moves"] else ""
        summary = (f"Sent '{subject}' to {len(to)} recipients - balances as of {b['d_cur']:%d-%b-%y} "
                   f"from {FILE.name}. Total cash {tot}{dlt}{moves}.")
        if a.trigger_user and a.trigger_user != BRIAN_SLACK: slack(a.trigger_user, summary)
        slack(BRIAN_SLACK, summary + f" Triggered by {who}.")
    except Exception as e:
        say("ERROR", traceback.format_exc())
        err = f"CICO daily balances email FAILED ({type(e).__name__}: {str(e)[:200]}). Nothing was sent."
        if a.trigger_user and a.trigger_user != BRIAN_SLACK: slack(a.trigger_user, err + " Brian has been notified.")
        slack(BRIAN_SLACK, err + f" Triggered by {who}. Log: treasury\\cico_daily_email.log")
        sys.exit(1)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
