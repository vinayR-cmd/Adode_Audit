"""
common.py — shared, dependency-free helpers for the brand-ai-readiness-audit
marketplace.

Standard library only (urllib, html.parser, re, json). No third-party packages,
so every skill is portable and install-free. All network access is read-only
GET, with a descriptive User-Agent, short timeouts and one bounded retry.

The unit every analyzer consumes is a "page bundle": the result of one polite
crawl, so the site is fetched once and each concern skill analyzes the same
captured bytes rather than re-fetching.

Nothing in here raises on network or parse failure. Every failure becomes a
recorded fact ("error", "blocked", "not_verified") so one bad page can never
abort an audit, and an unknown is never silently converted into a defect.
"""

import datetime
import gzip
import io
import json
import re
import socket
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag, urlparse

USER_AGENT = (
    "brand-ai-readiness-audit/1.0 (+read-only AI-discoverability auditor; "
    "respects robots.txt)"
)
DEFAULT_TIMEOUT = 10          # per-request seconds (robustness rule 2)
MAX_BYTES = 3_000_000         # cap per page (robustness rule 8)
MAX_REDIRECTS = 5             # (robustness rule 3)
RETRY_BACKOFF = 1.5           # seconds before the single retry


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Budget                                                                       #
# --------------------------------------------------------------------------- #
class Budget:
    """Wall-clock budget guard so the whole audit stays inside its time box."""

    def __init__(self, seconds=240):
        self.seconds = seconds
        self.start = time.time()

    def elapsed(self):
        return time.time() - self.start

    def remaining(self):
        return max(0.0, self.seconds - self.elapsed())

    def exhausted(self, reserve=15.0):
        """True when we should stop sampling new pages and write the report."""
        return self.remaining() <= reserve


# --------------------------------------------------------------------------- #
# Networking (read-only)                                                       #
# --------------------------------------------------------------------------- #
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable urllib's automatic redirects so we can record the chain."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _read_body(resp):
    raw = resp.read(MAX_BYTES + 1)
    truncated = len(raw) > MAX_BYTES
    raw = raw[:MAX_BYTES]
    if (resp.headers.get("Content-Encoding", "") or "").lower() == "gzip":
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except OSError:
            pass  # not actually gzip, or truncated mid-stream: keep the raw bytes
    return raw, truncated


_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w\-]+)""", re.I)


def decode_body(raw, content_type):
    """Charset from headers, else <meta charset>, else utf-8 — never raises."""
    charset = None
    m = re.search(r"charset=\s*\"?([\w\-]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    if not charset:
        m2 = _META_CHARSET_RE.search(raw[:4096])
        if m2:
            charset = m2.group(1).decode("ascii", "ignore")
    for candidate in (charset, "utf-8", "latin-1"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate, errors="replace"), (charset or "utf-8")
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _single_request(url, timeout):
    """One HTTP GET with no redirect following. Returns (resp_like, error_str)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "*",
    })
    try:
        return _OPENER.open(req, timeout=timeout), None
    except urllib.error.HTTPError as e:
        return e, None                      # 4xx/5xx are responses, not crashes
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        return None, "network_error: %s" % (reason,)
    except (ValueError, OSError) as e:      # malformed URL, TLS, socket issues
        return None, "request_error: %s" % (e,)
    except Exception as e:                  # last-resort guard: never crash a run
        return None, "unexpected_error: %s" % (e,)


def fetch(url, timeout=DEFAULT_TIMEOUT, max_redirects=MAX_REDIRECTS, retry=True):
    """
    GET a URL read-only, following redirects manually so the chain is visible.

    Returns a dict — never raises:
      url, final_url, status, headers(lowercased), text, raw_len, truncated,
      content_type, redirect_chain[], redirect_loop, cross_domain_redirect,
      encoding, error, elapsed
    """
    out = {
        "url": url, "final_url": url, "status": None, "headers": {},
        "text": "", "raw_len": 0, "truncated": False, "content_type": "",
        "redirect_chain": [], "redirect_loop": False,
        "cross_domain_redirect": False, "encoding": None,
        "error": None, "elapsed": 0.0,
    }
    started = time.time()
    current = url
    seen = set()
    attempts_left = 2 if retry else 1

    for _ in range(max_redirects + 1):
        if current in seen:
            out["redirect_loop"] = True
            out["error"] = "redirect_loop"
            break
        seen.add(current)

        resp, err = _single_request(current, timeout)
        if resp is None:
            attempts_left -= 1
            if attempts_left > 0:
                time.sleep(RETRY_BACKOFF)
                resp, err = _single_request(current, timeout)
            if resp is None:
                out["error"] = err
                out["final_url"] = current
                break

        status = resp.getcode() if hasattr(resp, "getcode") else getattr(resp, "code", None)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        out["status"] = status
        out["headers"] = headers
        out["final_url"] = current
        out["content_type"] = (headers.get("content-type", "") or "").split(";")[0].strip().lower()

        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            nxt = urldefrag(urljoin(current, headers["location"]))[0]
            out["redirect_chain"].append({"from": current, "status": status, "to": nxt})
            try:
                resp.close()
            except Exception:
                pass
            if not same_site(url, nxt):
                out["cross_domain_redirect"] = True
            current = nxt
            continue

        try:
            raw, truncated = _read_body(resp)
        except Exception as e:
            out["error"] = "read_error: %s" % (e,)
            raw, truncated = b"", False
        finally:
            try:
                resp.close()
            except Exception:
                pass
        out["raw_len"] = len(raw)
        out["truncated"] = truncated
        text, enc = decode_body(raw, headers.get("content-type", ""))
        out["text"] = text
        out["encoding"] = enc
        if status and status >= 400 and not out["error"]:
            out["error"] = "http_error_%s" % status
        break
    else:
        out["error"] = "too_many_redirects"

    out["elapsed"] = round(time.time() - started, 2)
    return out


def is_html(res):
    ct = res.get("content_type") or ""
    if ct:
        return "html" in ct or "xhtml" in ct
    return res.get("text", "").lstrip()[:1] == "<"


# --------------------------------------------------------------------------- #
# Anti-bot / login-wall detection (robustness rules 5 and 14)                   #
# --------------------------------------------------------------------------- #
_CHALLENGE_MARKERS = [
    "just a moment", "cf-browser-verification", "cf_chl", "cf-chl-",
    "checking your browser", "attention required! | cloudflare",
    "enable javascript and cookies to continue", "_incapsula_",
    "incident id:", "perimeterx", "px-captcha", "captcha-delivery",
    "recaptcha", "hcaptcha", "access denied", "request unsuccessful",
    "ddos protection by", "akamai reference", "reference #", "bot detection",
]


def detect_bot_block(res):
    """
    Return a reason string when the response looks like anti-bot protection
    rather than the site's real content, else None. Conservative on purpose:
    a plain 403 with a normal-sized body is NOT called a block.
    """
    status = res.get("status")
    body = (res.get("text") or "")
    low = body[:20000].lower()
    server = (res.get("headers", {}).get("server", "") or "").lower()

    hits = [m for m in _CHALLENGE_MARKERS if m in low]
    if status in (403, 429, 503) and hits:
        return "challenge page (%s) with HTTP %s" % (hits[0], status)
    if status in (400, 401, 403, 404, 405, 410, 429, 451, 503) and len(body.strip()) < 200:
        edge = next((s for s in ("cloudflare", "akamai", "fastly", "incapsula",
                                 "imperva", "sucuri", "cloudfront", "varnish")
                     if s in server), None)
        return ("HTTP %s returned a %d-byte body%s — a non-content response, most "
                "likely edge/anti-bot deflection rather than the site's own page"
                % (status, len(body.strip()),
                   " from an edge server (%s)" % edge if edge else ""))
    if status in (401, 403) and len(body.strip()) < 1500:
        return "HTTP %s with a near-empty body (%d bytes) — likely anti-bot/WAF block" % (
            status, len(body.strip()))
    if status in (403, 503) and ("cloudflare" in server or "cloudflare" in low[:4000]):
        return "HTTP %s served by Cloudflare edge — likely bot challenge" % status
    if status == 429:
        return "HTTP 429 rate limited"
    if hits and status == 200 and len(body) < 20000:
        return "challenge-style page markers (%s) on a 200 response" % hits[0]
    return None


_LOGIN_MARKERS = ["sign in", "log in", "login", "iniciar sesión", "connexion",
                  "anmelden", "accedi", "ログイン", "登录", "entrar"]


def detect_login_wall(parsed, res):
    """True when a page looks like an auth wall rather than public content."""
    has_password = any((i.get("type", "") or "").lower() == "password"
                       for i in parsed.get("inputs", []))
    if not has_password:
        return None
    if parsed.get("word_count", 0) < 250:
        return "password field with only %d words of content — authenticated area" % (
            parsed.get("word_count", 0))
    title = (parsed.get("title", "") or "").lower()
    if any(m in title for m in _LOGIN_MARKERS):
        return "login page (title: %r)" % parsed.get("title", "")[:80]
    return None


# --------------------------------------------------------------------------- #
# robots.txt                                                                   #
# --------------------------------------------------------------------------- #
AI_BOTS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Perplexity-User",
    "Google-Extended", "ClaudeBot", "Claude-Web", "Claude-SearchBot",
    "anthropic-ai", "CCBot", "Applebot-Extended", "Bytespider", "Amazonbot",
    "meta-externalagent", "cohere-ai", "Diffbot", "Timpibot", "YouBot",
]


class Robots:
    """
    Minimal, dependency-free robots.txt model.

    Groups are parsed as (user-agents -> rules). Matching follows the usual
    convention: the most specific matching user-agent group wins, else `*`.
    Path matching supports the `*` wildcard and `$` anchor.
    """

    def __init__(self, text=None, status=None, error=None):
        self.text = text or ""
        self.status = status
        self.error = error
        self.groups = []          # [{"agents": [...], "allow": [], "disallow": [], "delay": float|None}]
        self.sitemaps = []
        self.exists = bool(text) and status == 200
        if self.exists:
            self._parse()

    def _parse(self):
        cur = None
        expecting_agent = False
        for line in self.text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, value = line.split(":", 1)
            field = field.strip().lower()
            value = value.strip()
            if field == "user-agent":
                if cur is None or not expecting_agent:
                    cur = {"agents": [], "allow": [], "disallow": [], "delay": None}
                    self.groups.append(cur)
                cur["agents"].append(value.lower())
                expecting_agent = True
                continue
            expecting_agent = False
            if field == "sitemap":
                self.sitemaps.append(value)
            elif cur is None:
                continue
            elif field == "disallow":
                cur["disallow"].append(value)
            elif field == "allow":
                cur["allow"].append(value)
            elif field == "crawl-delay":
                try:
                    cur["delay"] = float(value)
                except ValueError:
                    pass

    # -- matching ----------------------------------------------------------
    @staticmethod
    def _rule_matches(rule, path):
        if rule == "":
            return False
        pattern = re.escape(rule).replace(r"\*", ".*")
        if pattern.endswith(r"\$"):
            pattern = pattern[:-2] + "$"
        return re.match(pattern, path) is not None

    def group_for(self, agent):
        agent = agent.lower()
        best, best_len = None, -1
        for g in self.groups:
            for a in g["agents"]:
                if a == "*" and best_len < 0:
                    best, best_len = g, 0
                elif a != "*" and (a in agent or agent in a) and len(a) > best_len:
                    best, best_len = g, len(a)
        return best

    def allowed(self, url, agent=USER_AGENT):
        """True when `agent` may fetch `url`. Missing/broken robots.txt = allowed."""
        if not self.exists:
            return True
        path = urlparse(url).path or "/"
        if urlparse(url).query:
            path += "?" + urlparse(url).query
        g = self.group_for(agent)
        if not g:
            return True
        best_dis = max((len(r) for r in g["disallow"] if self._rule_matches(r, path)),
                       default=-1)
        best_allow = max((len(r) for r in g["allow"] if self._rule_matches(r, path)),
                         default=-1)
        if best_dis < 0:
            return True
        return best_allow >= best_dis

    def crawl_delay(self, agent=USER_AGENT):
        g = self.group_for(agent)
        return (g or {}).get("delay")

    def ai_bot_status(self):
        """
        Per-AI-bot verdict on the site root and on a representative deep path.
        Returns {bot: {"root": bool, "deep": bool, "rules": [...]}}.
        """
        out = {}
        for bot in AI_BOTS:
            g = self.group_for(bot)
            if g is None:
                out[bot] = {"blocked_all": False, "explicit": False, "rules": []}
                continue
            explicit = any(a != "*" and (a in bot.lower() or bot.lower() in a)
                           for a in g["agents"])
            blocked_all = any(r.strip() == "/" for r in g["disallow"]) and \
                not any(self._rule_matches(r, "/") for r in g["allow"])
            out[bot] = {
                "blocked_all": blocked_all,
                "explicit": explicit,
                "rules": g["disallow"][:6],
            }
        return out


def fetch_robots(origin, timeout=DEFAULT_TIMEOUT):
    res = fetch(urljoin(origin, "/robots.txt"), timeout=timeout)
    if res["error"] and res["status"] is None:
        return Robots(error=res["error"]), res
    if res["status"] != 200 or not is_texty(res):
        return Robots(status=res["status"], error=res["error"]), res
    return Robots(text=res["text"], status=200), res


def is_texty(res):
    ct = res.get("content_type", "")
    return (not ct) or ct.startswith("text/") or "xml" in ct or "json" in ct


# --------------------------------------------------------------------------- #
# Site identity helpers                                                        #
# --------------------------------------------------------------------------- #
_MULTI_SUFFIXES = {
    # UK / IE
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "sch.uk",
    # India
    "co.in", "ac.in", "gov.in", "edu.in", "net.in", "org.in", "res.in",
    "firm.in", "gen.in", "ind.in",
    # Asia-Pacific
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp", "co.kr", "or.kr",
    "co.nz", "org.nz", "net.nz", "govt.nz", "ac.nz", "school.nz",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "asn.au", "id.au",
    "com.sg", "edu.sg", "gov.sg", "com.cn", "net.cn", "org.cn", "gov.cn",
    "com.hk", "org.hk", "com.my", "com.ph", "co.th", "in.th", "com.tw",
    "com.vn", "co.id", "or.id",
    # Americas
    "com.br", "net.br", "org.br", "gov.br", "com.mx", "com.ar", "com.co",
    "com.pe", "com.uy", "com.ve",
    # Europe / Middle East / Africa
    "com.tr", "gov.tr", "co.za", "org.za", "gov.za", "ac.za", "co.il",
    "org.il", "ac.il", "gov.il", "com.es", "com.pl", "com.ua", "com.ru",
    "co.ke", "co.ug", "com.ng", "com.eg", "com.sa", "com.ae",
}


def registrable(host):
    host = (host or "").lower().split(":")[0].strip(".")
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host
    if ".".join(parts[-2:]) in _MULTI_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(a, b):
    return registrable(urlparse(a).netloc) == registrable(urlparse(b).netloc)


def normalize_url(raw):
    """Accept 'example.com', 'http://example.com/x#y' -> canonical absolute URL."""
    u = (raw or "").strip()
    if not u:
        raise ValueError("empty URL")
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", u, re.I):
        u = "https://" + u
    parts = urlparse(u)
    if parts.scheme not in ("http", "https"):
        raise ValueError("unsupported scheme: %s" % parts.scheme)
    if not parts.netloc:
        raise ValueError("no host in URL: %r" % raw)
    return urldefrag(u)[0]


def origin_of(url):
    p = urlparse(url)
    return "%s://%s" % (p.scheme, p.netloc)


def path_depth(url):
    return len([s for s in urlparse(url).path.strip("/").split("/") if s])


# --------------------------------------------------------------------------- #
# HTML parsing (no bs4)                                                        #
# --------------------------------------------------------------------------- #
class _Extractor(HTMLParser):
    """Single-pass HTML walker collecting the signals every analyzer needs."""

    _SKIP_TEXT_IN = {"script", "style", "template", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.early_text_parts = []   # text before the ~first 1200 visible words
        self.title = ""
        self.links = []              # (href, anchor_text)
        self.metas = []
        self.jsonld_raw = []
        self.images = []
        self.inputs = []
        self.headings = []           # (tag, text)
        self.has_search_input = False
        self.has_viewport = False
        self.viewport_content = ""
        self.script_src_count = 0
        self.external_script_count = 0
        self.inline_script_bytes = 0
        self.microdata_itemtypes = []
        self.rel_canonical = None
        self.rel_alternate_langs = []
        self.html_lang = None
        self.nav_links = []
        self.iframe_count = 0
        self.form_count = 0
        self._stack = []
        self._grab = None
        self._cur_heading_tag = None
        self._nav_stack = []
        self._chars = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag not in ("br", "img", "meta", "link", "input", "hr", "source", "area"):
            self._stack.append(tag)
        if tag == "html" and a.get("lang"):
            self.html_lang = a["lang"]
        elif tag == "title":
            self._grab = ("title", [])
        elif tag == "a" and a.get("href"):
            self.links.append([a["href"], ""])
            if self._nav_stack:
                self.nav_links.append(a["href"])
        elif tag == "meta":
            self.metas.append(a)
            if a.get("name", "").lower() == "viewport":
                self.has_viewport = True
                self.viewport_content = a.get("content", "")
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "canonical" in rel and a.get("href"):
                self.rel_canonical = a["href"]
            if "alternate" in rel and a.get("hreflang"):
                self.rel_alternate_langs.append(a["hreflang"])
        elif tag == "img":
            self.images.append(a)
        elif tag == "iframe":
            self.iframe_count += 1
        elif tag == "form":
            self.form_count += 1
        elif tag == "input":
            self.inputs.append(a)
            t = (a.get("type", "") or "").lower()
            blob = (a.get("name", "") + a.get("id", "") +
                    a.get("placeholder", "") + a.get("aria-label", "")).lower()
            if t == "search" or "search" in blob or "recherche" in blob or "buscar" in blob:
                self.has_search_input = True
        elif tag == "script":
            if a.get("src"):
                self.script_src_count += 1
                if a["src"].startswith("http") or a["src"].startswith("//"):
                    self.external_script_count += 1
            if (a.get("type", "") or "").lower() in (
                    "application/ld+json", "application/json+ld"):
                self._grab = ("jsonld", [])
        elif tag in ("h1", "h2", "h3"):
            self._grab = ("h", [])
            self._cur_heading_tag = tag
        # Navigation containers: the semantic elements, ARIA roles, and the very
        # common class-named wrappers. Sites that ship a perfectly usable menu in
        # a <div class="site-header"> must not be reported as having no navigation.
        if (tag in ("nav", "header")
                or (a.get("role", "") or "").lower() == "navigation"
                or (tag in ("div", "ul", "section", "aside", "footer")
                    and any(k in (a.get("class", "") or "").lower()
                            for k in ("nav", "menu", "header")))):
            self._nav_stack.append(tag)
        if a.get("itemtype"):
            self.microdata_itemtypes.append(a["itemtype"])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self._stack:
            while self._stack:
                popped = self._stack.pop()
                if popped == tag:
                    break
        if self._nav_stack and self._nav_stack[-1] == tag:
            self._nav_stack.pop()
        if self._grab:
            kind, acc = self._grab
            joined = "".join(acc).strip()
            if kind == "title" and tag == "title":
                self.title = joined
                self._grab = None
            elif kind == "jsonld" and tag == "script":
                if joined:
                    self.jsonld_raw.append(joined)
                self._grab = None
            elif kind == "h" and tag in ("h1", "h2", "h3"):
                if joined:
                    self.headings.append((self._cur_heading_tag, joined))
                self._grab = None
                self._cur_heading_tag = None

    def handle_data(self, data):
        if self._grab:
            self._grab[1].append(data)
            if self._grab[0] != "h":
                return
        if any(t in self._SKIP_TEXT_IN for t in self._stack):
            if "script" in self._stack:
                self.inline_script_bytes += len(data)
            return
        s = data.strip()
        if not s:
            return
        self.text_parts.append(s)
        self._chars += len(s)
        if self._chars < 2500:
            self.early_text_parts.append(s)
        if self.links and self.links[-1][1] == "" and "a" in self._stack:
            self.links[-1][1] = s[:120]


def parse_html(html):
    """Run the extractor and return a normalized dict of page signals.

    Degrades gracefully: a malformed document yields whatever was parsed
    before the problem instead of raising (robustness rule 7).
    """
    p = _Extractor()
    parse_error = None
    try:
        p.feed(html or "")
        p.close()
    except Exception as e:
        parse_error = "html_parse_degraded: %s" % (e,)
    visible = re.sub(r"\s+", " ", " ".join(p.text_parts)).strip()
    early = re.sub(r"\s+", " ", " ".join(p.early_text_parts)).strip()
    return {
        "title": p.title,
        "visible_text": visible,
        "early_text": early,
        "word_count": len(visible.split()) if visible else 0,
        "links": [tuple(l) for l in p.links],
        "metas": p.metas,
        "jsonld_raw": p.jsonld_raw,
        "images": p.images,
        "inputs": p.inputs,
        "headings": p.headings,
        "has_search_input": p.has_search_input,
        "has_viewport": p.has_viewport,
        "viewport_content": p.viewport_content,
        "script_src_count": p.script_src_count,
        "external_script_count": p.external_script_count,
        "inline_script_bytes": p.inline_script_bytes,
        "microdata_itemtypes": p.microdata_itemtypes,
        "rel_canonical": p.rel_canonical,
        "rel_alternate_langs": p.rel_alternate_langs,
        "html_lang": p.html_lang,
        "nav_links": p.nav_links,
        "iframe_count": p.iframe_count,
        "form_count": p.form_count,
        "parse_error": parse_error,
    }


def parse_jsonld(blocks):
    """Parse raw JSON-LD strings into (objects, errors). Handles @graph + arrays."""
    objects, errors = [], []
    for raw in blocks:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as e:
            errors.append(str(e)[:160])
            continue
        stack = [data]
        guard = 0
        while stack and guard < 2000:
            guard += 1
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if isinstance(node.get("@graph"), list):
                    stack.extend(node["@graph"])
                objects.append(node)
    return objects, errors


def jsonld_types(objects):
    types = set()
    for o in objects:
        t = o.get("@type")
        if isinstance(t, list):
            types.update(str(x) for x in t)
        elif t:
            types.add(str(t))
    return types


def meta_content(metas, name=None, prop=None):
    for m in metas:
        if name and m.get("name", "").lower() == name.lower():
            return m.get("content", "")
        if prop and m.get("property", "").lower() == prop.lower():
            return m.get("content", "")
    return ""


def meta_robots(metas):
    return (meta_content(metas, name="robots") or "").lower()


# --------------------------------------------------------------------------- #
# Findings                                                                     #
# --------------------------------------------------------------------------- #
SEVERITIES = ("critical", "high", "medium", "low")


def finding(title, severity, category, evidence, action_summary,
            priority=None, how="", confidence="high", mechanism="",
            root_cause=None, pages=None, check=""):
    """Construct a finding in the shape the orchestrator expects."""
    return {
        "title": title,
        "severity": severity if severity in SEVERITIES else "medium",
        "category": category,            # 'discoverability' | 'engagement'
        "confidence": confidence,        # 'high' | 'medium' | 'low'
        "mechanism": mechanism,          # WHY this affects reach/read/extract
        "evidence": evidence,            # concrete: URL + status/count/snippet
        "affected_pages": pages or [],
        "root_cause": root_cause,        # dedupe key for sitewide template issues
        "check": check,
        "suggested_action": {
            "summary": action_summary,
            "priority": priority or severity,
            "how": how,
        },
    }


def not_verified(check, reason, target=""):
    return {"check": check, "target": target, "reason": reason}


def opportunity(title, category, rationale, action, effort="medium"):
    return {
        "title": title,
        "type": "opportunity",
        "category": category,
        "rationale": rationale,
        "suggested_action": {"summary": action, "effort": effort},
    }


# --------------------------------------------------------------------------- #
# Analyzer CLI plumbing                                                        #
# --------------------------------------------------------------------------- #
def load_bundle_from_args(argv, default_pages=10):
    """
    Shared CLI entry for analyzers:
      --bundle path.json   (preferred; produced once by the orchestrator's crawl)
      --url https://...    (standalone convenience; does its own small crawl)
    """
    import argparse
    import os
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle")
    ap.add_argument("--url")
    ap.add_argument("--max-pages", type=int, default=default_pages)
    args = ap.parse_args(argv)

    if args.bundle:
        with open(args.bundle, "r", encoding="utf-8") as fh:
            return json.load(fh)
    if args.url:
        crawl = _import_crawl()
        if crawl is not None:
            return crawl.crawl(normalize_url(args.url), max_pages=args.max_pages)
        return single_page_bundle(args.url)
    raise SystemExit("Provide --bundle <path> or --url <site>")


def _import_crawl():
    """Find the orchestrator's crawl.py whether or not we're run from there."""
    import importlib.util
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "crawl.py"),
        os.path.join(here, "..", "..", "audit-orchestrator", "scripts", "crawl.py"),
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("crawl", path)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                return mod
            except Exception:
                return None
    return None


def single_page_bundle(url):
    """Minimal one-page bundle for standalone analyzer runs (no crawl.py)."""
    url = normalize_url(url)
    res = fetch(url)
    html_ok = is_html(res)
    return {
        "site": registrable(urlparse(url).netloc),
        "start_url": url,
        "origin": origin_of(url),
        "fetched_at": utcnow(),
        "robots": {"exists": False, "note": "not fetched in standalone mode"},
        "sitemap": {"found": False, "urls": []},
        "pages": [{
            "url": url, "final_url": res["final_url"], "status": res["status"],
            "headers": res["headers"], "html": res["text"] if html_ok else "",
            "content_type": res["content_type"], "bytes": res["raw_len"],
            "error": res["error"], "robots_allowed": True, "is_html": html_ok,
            "redirect_chain": res["redirect_chain"],
            "blocked_reason": detect_bot_block(res),
        }],
        "notes": ["standalone single-page fetch (no crawl.py present)"],
        "not_verified": [],
    }


def html_pages(bundle):
    """
    Pages that yielded real, analyzable content.

    Excludes error pages (a 404 body is not the site's content), bot challenges
    and login walls — analyzing those as if they were content is how a static
    auditor invents findings about pages it never actually saw.
    """
    out = []
    for p in bundle.get("pages", []):
        if not (p.get("is_html") and p.get("html")):
            continue
        if p.get("blocked_reason") or p.get("login_wall"):
            continue
        status = p.get("status")
        if isinstance(status, int) and not (200 <= status < 300):
            continue
        out.append(p)
    return out


def get_parsed(page):
    """Parse (and memoize) a page's HTML inside the bundle."""
    if "_parsed" not in page:
        try:
            page["_parsed"] = parse_html(page.get("html", ""))
        except Exception as e:
            page["_parsed"] = parse_html("")
            page["_parsed"]["parse_error"] = "parse_failed: %s" % (e,)
    return page["_parsed"]


def emit(payload):
    import sys
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
