#!/usr/bin/env python3
"""Licence, copyright and GDPR scan of a project folder. Standard library only,
no network: it reads files and never connects anywhere.

    python3 legal_scan.py <folder>                        # findings; exit 1 on any error
    python3 legal_scan.py <folder> --json                 # the same, as JSON
    python3 legal_scan.py <folder> --skip replica/screens # a folder that is never shipped

What it looks for, each finding with file:line, a rule and what to do:

    asset-unregistered  an image, icon, font, sound, video or 3D model that is not in
                        credits.json — nobody can say where it comes from
    asset-licence       a credits.json entry whose licence forbids the use (non
                        commercial, no derivatives yet modified, all rights reserved,
                        unknown) or that lacks the credit its licence requires
    remote-media        an image, font or video loaded from another site (hotlink)
    private-link        a share link or a signed / tokenised URL: Drive, Dropbox,
                        OneDrive, WeTransfer, S3 or Azure signatures, chat attachments
    google-fonts        fonts served by Google: every visitor's IP goes to Google
    tracker             analytics, advertising and social pixels
    third-party-embed   YouTube, maps, social widgets, reCAPTCHA
    cdn                 scripts or styles loaded from a public CDN
    dependency-licence  a dependency under AGPL, SSPL, a non-commercial or an unknown
                        licence (error) or a copyleft one (warning)
    copied-code         Stack Overflow links, GPL headers, someone else's copyright
    personal-data       e-mail addresses, phone numbers, IBANs in code or test data
    legal-pages         a site that collects personal data with no privacy policy,
                        a public site with no legal notice
    licence-file        no LICENSE file

The register of assets is credits.json, at the root of the scanned folder:

    {"assets": [{"path": "public/img/hero.webp", "source": "https://unsplash.com/photos/…",
                 "author": "Jane Doe", "licence": "Unsplash"},
                {"path": "public/icons/*.svg", "source": "https://lucide.dev",
                 "author": "Lucide Contributors", "licence": "ISC"},
                {"path": "src/assets/logo.svg", "source": "original", "licence": "original"}],
     "dependencies": {"some-gpl-tool": "used at build time only, never distributed"}}

A finding is a lead, not a verdict: the legal specialist confirms it. But no
error is left in a delivered project.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

try:
    import tomllib
except ImportError:                      # Python < 3.11: pyproject.toml is skipped
    tomllib = None


# ── What counts as what ──────────────────────────────────────────────────────

SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__", "dist", "build",
    ".next", ".nuxt", ".svelte-kit", ".output", "out", "coverage", ".cache", ".turbo",
    ".parcel-cache", "target", "vendor", ".idea", ".vscode", ".claude", ".jarvis", ".agents",
}
MEDIA_EXT = {
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp", ".tif", ".tiff",
    ".heic",
    # fonts
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    # sound and video
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".mp4", ".webm", ".mov", ".mkv",
    # 3D
    ".glb", ".gltf", ".fbx", ".obj",
}
MARKUP_EXT = {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".php", ".erb",
              ".twig", ".njk", ".hbs", ".liquid"}
CODE_EXT = MARKUP_EXT | {".css", ".scss", ".sass", ".less", ".js", ".mjs", ".cjs", ".ts", ".py",
                         ".rb", ".go", ".java", ".kt", ".swift", ".dart", ".cs", ".rs"}
DATA_EXT = {".json", ".yml", ".yaml", ".toml", ".xml", ".csv", ".sql"}
DOC_EXT = {".md", ".mdx"}
TEXT_EXT = CODE_EXT | DATA_EXT | DOC_EXT | {".svg"}
SKIP_FILES = {"credits.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
              "composer.lock", "Pipfile.lock", "Cargo.lock"}
MAX_BYTES = 2_000_000

# Asset licences, by key() of the name written in credits.json.
FREE_LICENCES = {"original", "generated", "cc0", "cc0-1-0", "public-domain", "pdm", "unsplash",
                 "pexels", "pixabay"}
NOTICE_LICENCES = {"mit", "isc", "apache-2-0", "bsd-2-clause", "bsd-3-clause", "0bsd", "zlib",
                   "ofl", "ofl-1-1", "ubuntu-font-licence", "ubuntu-font-license"}
# A third party's logo or badge used as its brand guidelines allow ("Sign in with
# Google", payment and store badges): the source must be those guidelines.
BRAND_LICENCES = {"brand-guidelines"}
PAID_LICENCES = {"commercial", "purchased", "royalty-free", "stock"}
FORBIDDEN_LICENCES = {"all-rights-reserved", "unknown", "proprietary", "editorial",
                      "editorial-use-only", "personal-use", "personal-use-only", "free-for-personal-use"}

PRIVATE_HOSTS = {
    "drive.google.com": "Google Drive", "drive.usercontent.google.com": "Google Drive",
    "docs.google.com": "Google Docs", "dropbox.com": "Dropbox", "www.dropbox.com": "Dropbox",
    "dl.dropboxusercontent.com": "Dropbox", "1drv.ms": "OneDrive", "onedrive.live.com": "OneDrive",
    "wetransfer.com": "WeTransfer", "we.tl": "WeTransfer", "mega.nz": "MEGA",
    "cdn.discordapp.com": "a Discord attachment", "media.discordapp.net": "a Discord attachment",
    "files.slack.com": "a Slack file", "private-user-images.githubusercontent.com": "a private GitHub image",
}
# Query parameters of a URL that only works for whoever it was issued to. (API keys
# in URLs are a security matter: the cyber specialist's secret scanner finds them.)
SIGNED_QUERY = {"x-amz-signature", "x-amz-credential", "x-goog-signature", "x-goog-credential",
                "signature", "sig", "token", "access_token", "auth", "sessionid", "jwt"}
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
TRACKER_HOSTS = {
    "googletagmanager.com", "google-analytics.com", "analytics.google.com", "doubleclick.net",
    "googlesyndication.com", "googleadservices.com", "connect.facebook.net", "static.hotjar.com",
    "script.hotjar.com", "clarity.ms", "snap.licdn.com", "px.ads.linkedin.com",
    "analytics.tiktok.com", "cdn.segment.com", "cdn.mxpnl.com", "cdn.amplitude.com",
    "js.hs-scripts.com", "js.hs-analytics.net", "static.ads-twitter.com", "ct.pinterest.com",
    "bat.bing.com", "mc.yandex.ru",
}
TRACKER_CALLS = re.compile(r"\b(gtag|fbq|ttq|_hsq|hj)\s*\(|\bga\(\s*['\"]create|dataLayer\.push")
EMBEDS = {
    "youtube.com/embed": "YouTube: use youtube-nocookie.com and load it on click",
    "youtube.com/iframe_api": "YouTube: use youtube-nocookie.com and load it on click",
    "player.vimeo.com": "Vimeo: add dnt=1 and load it on click",
    "google.com/maps/embed": "Google Maps: load it on click, or use OpenStreetMap",
    "maps.googleapis.com/maps/api": "Google Maps: load it on click, or use OpenStreetMap",
    "platform.twitter.com": "an X / Twitter widget: load it on click",
    "instagram.com/embed": "an Instagram embed: load it on click",
    "google.com/recaptcha": "reCAPTCHA sends data to Google: say so in the privacy policy",
    "gstatic.com/recaptcha": "reCAPTCHA sends data to Google: say so in the privacy policy",
}
CDN_HOSTS = {"cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com", "code.jquery.com",
             "stackpath.bootstrapcdn.com", "maxcdn.bootstrapcdn.com", "cdn.tailwindcss.com",
             "ajax.googleapis.com", "kit.fontawesome.com", "use.fontawesome.com", "esm.sh",
             "cdn.skypack.dev", "use.typekit.net"}
IMAGE_HOSTS = {"images.unsplash.com", "source.unsplash.com", "images.pexels.com", "i.imgur.com",
               "pbs.twimg.com", "lh3.googleusercontent.com", "i.pinimg.com", "media.giphy.com",
               "encrypted-tbn0.gstatic.com", "upload.wikimedia.org", "picsum.photos",
               "placehold.co", "via.placeholder.com", "placekitten.com", "loremflickr.com"}
CONSENT_TOOLS = re.compile(r"tarteaucitron|axeptio|didomi|cookiebot|onetrust|klaro|orejime|"
                           r"cookieconsent|usercentrics|iubenda|gtag\(\s*['\"]consent", re.I)

URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]{}`\\|^]+", re.I)
PROTOCOL_RELATIVE_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']//([^"'\s>]+)|url\(\s*["']?//([^"')\s]+)""", re.I)
MD_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\(\s*<?(https?://[^\s)>]+)|<img[^>]+src\s*=\s*[\"'](https?://[^\"']+)", re.I)
EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,}))\b")
PHONE_RE = re.compile(r"(?<![\d+])(?:\+33[\s.-]?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
FAKE_PHONE_RE = re.compile(r"0[1-9](?:[\s.-]?00){4}|0123456789|01[\s.-]?23[\s.-]?45[\s.-]?67[\s.-]?89")
IBAN_RE = re.compile(r"\bFR\d{2}(?:[ ]?[0-9A-Z]{4}){5}[ ]?[0-9A-Z]{3}\b")
FAKE_DOMAINS = re.compile(
    r"(^|\.)(example|exemple|test|invalid|localhost|local|domain|yourdomain|votredomaine|company|"
    r"acme|foo|bar)\.[a-z]+$|^(example|exemple|test|localhost|invalid|local)$", re.I)
ROLE_ADDRESSES = {"git", "noreply", "no-reply", "donotreply", "ne-pas-repondre"}
FILE_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "js", "ts", "css", "json", "md", "html",
             "vue", "py", "map", "woff", "woff2"}
COLLECTS_DATA = re.compile(
    r"""type\s*=\s*["']?(email|tel|password)\b|name\s*=\s*["'](e-?mail|phone|telephone|téléphone|"""
    r"""firstname|lastname|nom|prenom|prénom|address|adresse)["']""", re.I)
PRIVACY_PATH = re.compile(r"confidentialit|privacy|donnees-personnelles|données-personnelles|rgpd",
                          re.I)
PRIVACY_LINK = re.compile(r"""(?:href|to|path)\s*[=:]\s*\{?["'`][^"'`]*"""
                          r"""(?:confidentialit|privacy|donnees-personnelles)""", re.I)
LEGAL_PAGE = re.compile(r"mentions-l[eé]gales|mentions_legales|mentionslegales|legal-notice|"
                        r"imprint|/legal\b", re.I)


def key(text) -> str:
    """Lower case, no accents, dashes: "CC BY 4.0" -> "cc-by-4-0"."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ── Findings ─────────────────────────────────────────────────────────────────

class Findings:
    def __init__(self):
        self.items: list[dict] = []
        self._seen: set[tuple] = set()

    def add(self, level: str, rule: str, file: str, line: int, message: str) -> None:
        mark = (rule, file, line, message)
        if mark not in self._seen:
            self._seen.add(mark)
            self.items.append({"level": level, "rule": rule, "file": file, "line": line,
                               "message": message})

    def error(self, rule: str, file: str, line: int, message: str) -> None:
        self.add("error", rule, file, line, message)

    def warn(self, rule: str, file: str, line: int, message: str) -> None:
        self.add("warning", rule, file, line, message)

    @property
    def errors(self) -> list[dict]:
        return [f for f in self.items if f["level"] == "error"]

    @property
    def warnings(self) -> list[dict]:
        return [f for f in self.items if f["level"] == "warning"]


# ── Walking the folder ───────────────────────────────────────────────────────

def project_files(root: Path, skip: list[str]) -> list[str]:
    """Every file of the project, as paths relative to root, minus what is never shipped."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()

        def rel(name: str) -> str:
            return name if rel_dir == "." else f"{rel_dir}/{name}"

        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not any(_under(rel(d), s) for s in skip))
        out += [rel(n) for n in sorted(filenames) if not any(_under(rel(n), s) for s in skip)]
    return out


def _under(path: str, folder: str) -> bool:
    folder = folder.strip("/")
    return bool(folder) and (path == folder or path.startswith(folder + "/"))


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ── credits.json: the register of assets ───────────────────────────────────

def load_credits(root: Path, found: Findings) -> dict:
    path = root / "credits.json"
    if not path.is_file():
        return {"assets": [], "dependencies": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        found.error("asset-licence", "credits.json", 0, f"not valid JSON ({e})")
        return {"assets": [], "dependencies": {}}
    if not isinstance(data, dict):
        found.error("asset-licence", "credits.json", 0, "must be an object with an \"assets\" list")
        return {"assets": [], "dependencies": {}}
    assets = [a for a in data.get("assets") or [] if isinstance(a, dict) and a.get("path")]
    deps = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    return {"assets": assets, "dependencies": deps}


def check_credit(entry: dict, found: Findings) -> None:
    """Does the licence written for this asset allow its use, and is the credit there?"""
    where, path = "credits.json", entry["path"]
    lic = key(entry.get("licence") or entry.get("license"))
    source = str(entry.get("source") or "").strip()
    if not source:
        found.error("asset-licence", where, 0, f"{path}: no source — a URL, or \"original\" for "
                                               "what the team made")
    if not lic:
        found.error("asset-licence", where, 0, f"{path}: no licence")
        return
    if lic in FREE_LICENCES or lic in NOTICE_LICENCES:
        if lic in NOTICE_LICENCES and not entry.get("author"):
            found.warn("asset-licence", where, 0, f"{path}: {lic} asks to keep the copyright notice — "
                                                  "name the author")
        return
    if lic in BRAND_LICENCES:
        if not source.startswith(("http://", "https://")):
            found.error("asset-licence", where, 0, f"{path}: a brand asset needs the URL of the brand "
                                                   "guidelines that allow it as its source")
        return
    if lic in PAID_LICENCES:
        if not str(entry.get("proof") or "").strip():
            found.error("asset-licence", where, 0, f"{path}: a paid licence needs its proof (order "
                                                   "or licence number) in \"proof\"")
        return
    if lic in FORBIDDEN_LICENCES:
        found.error("asset-licence", where, 0, f"{path}: licence \"{entry.get('licence')}\" does not "
                                               "allow this use — replace the asset")
        return
    if lic.startswith("cc-by"):
        if "-nc" in lic:
            found.error("asset-licence", where, 0, f"{path}: {entry.get('licence')} forbids commercial "
                                                   "use — replace the asset")
            return
        if "-nd" in lic and entry.get("modified") is not False:
            found.error("asset-licence", where, 0, f"{path}: {entry.get('licence')} forbids changes — "
                                                   "use it untouched and set \"modified\": false, "
                                                   "or replace it")
        if not str(entry.get("attribution") or "").strip() or not entry.get("author"):
            found.error("asset-licence", where, 0, f"{path}: {entry.get('licence')} requires a credit — "
                                                   "fill author and attribution, and show it in the app")
        if "-sa" in lic:
            found.warn("asset-licence", where, 0, f"{path}: share-alike — a modified version must be "
                                                  "published under the same licence")
        return
    found.error("asset-licence", where, 0, f"{path}: unknown licence \"{entry.get('licence')}\" — use "
                                           "an SPDX id (CC0-1.0, CC-BY-4.0, MIT, OFL-1.1…), Unsplash, "
                                           "Pexels, original or commercial with a proof")


def registered(path: str, assets: list[dict]) -> bool:
    return any(path == a["path"] or fnmatch.fnmatch(path, a["path"]) for a in assets)


def check_assets(files: list[str], credits: dict, found: Findings) -> dict:
    assets = credits["assets"]
    for entry in assets:
        check_credit(entry, found)
    media = [f for f in files if Path(f).suffix.lower() in MEDIA_EXT]
    for f in media:
        if not registered(f, assets):
            found.error("asset-unregistered", f, 0, "not in credits.json: record its source, author "
                                                    "and licence, or replace it with an asset of your own")
    for entry in assets:
        p = entry["path"]
        if not p.startswith(("http://", "https://")) and not any(f == p or fnmatch.fnmatch(f, p)
                                                                 for f in media):
            found.warn("asset-licence", "credits.json", 0, f"{p}: matches no file — remove the entry")
    return {"media": len(media), "registered": sum(1 for f in media if registered(f, assets))}


# ── Text files: links, trackers, copied code, personal data ─────────────────

def scan_text(rel: str, text: str, credits: dict, owners: str, found: Findings,
              consent: bool) -> None:
    ext = Path(rel).suffix.lower()
    is_doc = ext in DOC_EXT
    remote_ok = [a["path"] for a in credits["assets"] if a["path"].startswith(("http://", "https://"))]
    for no, line in enumerate(text.splitlines(), 1):
        if len(line) > 5000:                            # minified or embedded data: skip
            continue
        urls = [m.group(0).rstrip(".,;:") for m in URL_RE.finditer(line)]
        urls += ["https://" + (m.group(1) or m.group(2)) for m in PROTOCOL_RELATIVE_RE.finditer(line)]
        for url in urls:
            check_url(rel, no, url, is_doc, remote_ok, consent, found)
        if is_doc:
            for m in MD_IMAGE_RE.finditer(line):
                url = m.group(1) or m.group(2)
                if not _remote_registered(url, remote_ok):
                    found.error("remote-media", rel, no, f"image loaded from {urlsplit(url).netloc}: "
                                                         "download it under a licence that allows it and "
                                                         "record it in credits.json, or remove it")
        if ext in CODE_EXT and TRACKER_CALLS.search(line):
            report_tracker(rel, no, "a tracking call", consent, found)
        if ext in CODE_EXT | DATA_EXT:
            check_personal_data(rel, no, line, found)
        if ext in CODE_EXT:
            check_copied_code(rel, no, line, owners, found)


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]


def _remote_registered(url: str, remote_ok: list[str]) -> bool:
    return any(url == p or url.startswith(p.rstrip("*")) or fnmatch.fnmatch(url, p) for p in remote_ok)


def check_url(rel: str, no: int, url: str, is_doc: bool, remote_ok: list[str], consent: bool,
              found: Findings) -> None:
    parts = urlsplit(url)
    host = _host(url)
    bare = host.removeprefix("www.")
    where = f"{bare}{parts.path}"
    if FAKE_DOMAINS.search(bare) or bare in ("127.0.0.1", "0.0.0.0"):
        return                                         # placeholders and local addresses

    if "@" in parts.netloc:
        found.error("private-link", rel, no, f"a URL with a login in it ({host}): remove the credentials")
        return
    private = PRIVATE_HOSTS.get(host) or PRIVATE_HOSTS.get(bare)
    if private or host.endswith(".sharepoint.com"):
        found.error("private-link", rel, no, f"a private share link ({private or 'SharePoint'}): put the "
                                             "file in the project under a licence that allows it, or "
                                             "remove the link")
        return
    query = {k.lower() for k in parse_qs(parts.query, keep_blank_values=True)}
    signed = sorted(query & SIGNED_QUERY)
    if signed:
        found.error("private-link", rel, no, f"a signed or tokenised URL ({', '.join(signed)} on "
                                             f"{host}): it is private and expires — never commit it")
        return
    if bare.endswith("figma.com") and re.match(r"/(file|design|proto)/", parts.path):
        found.warn("private-link", rel, no, "a Figma file link: check it is meant to be shared")
    if is_doc:
        return                                         # in docs, a link is only a link

    if host in FONT_HOSTS:
        found.error("google-fonts", rel, no, "fonts served by Google send every visitor's IP to Google "
                                             "(LG München, 20 Jan 2022): self-host the font files "
                                             "(OFL) and record them in credits.json")
        return
    if any(bare == t or bare.endswith("." + t) for t in TRACKER_HOSTS) or where.startswith("facebook.com/tr"):
        report_tracker(rel, no, bare, consent, found)
        return
    for pattern, advice in EMBEDS.items():
        if pattern in where:
            found.warn("third-party-embed", rel, no, advice)
            return
    if bare in CDN_HOSTS:
        found.warn("cdn", rel, no, f"loaded from {bare}: the visitor's IP goes to the CDN — install the "
                                   "package and bundle it")
        return
    if Path(parts.path).suffix.lower() in MEDIA_EXT or bare in IMAGE_HOSTS:
        if not _remote_registered(url, remote_ok):
            found.error("remote-media", rel, no, f"media loaded from {bare} (hotlink): download it under "
                                                 "a licence that allows it and record it in credits.json, "
                                                 "or draw your own")


def report_tracker(rel: str, no: int, what: str, consent: bool, found: Findings) -> None:
    if consent:
        found.warn("tracker", rel, no, f"{what}: check it only loads after the visitor's consent "
                                       "(CNIL guidelines on cookies and trackers)")
    else:
        found.error("tracker", rel, no, f"{what} with no consent manager: a tracker needs prior consent, "
                                        "refusing must be as easy as accepting — remove it or add consent")


def check_personal_data(rel: str, no: int, line: str, found: Findings) -> None:
    if Path(rel).name in ("package.json", "pyproject.toml", "composer.json", "setup.py", "setup.cfg"):
        return
    for m in EMAIL_RE.finditer(line):
        local, domain, tld = m.group(1).lower(), m.group(2), m.group(3).lower()
        if tld in FILE_TLDS or local in ROLE_ADDRESSES or FAKE_DOMAINS.search(domain):
            continue
        found.warn("personal-data", rel, no, "an e-mail address: use fake data (example.com, Faker) "
                                             "in code and test data")
        break
    if PHONE_RE.search(line) and not FAKE_PHONE_RE.search(line):
        found.warn("personal-data", rel, no, "a phone number: use fake data in code and test data")
    if IBAN_RE.search(line):
        found.warn("personal-data", rel, no, "an IBAN: never real bank details in a project")


def check_copied_code(rel: str, no: int, line: str, owners: str, found: Findings) -> None:
    low = line.lower()
    if "stackoverflow.com/" in low or "stackexchange.com/" in low:
        found.warn("copied-code", rel, no, "code from Stack Overflow is CC BY-SA: keep the link as "
                                           "credit, and the share-alike applies to that snippet")
    if re.search(r"gnu (affero |lesser )?general public license|spdx-license-identifier:\s*(a|l)?gpl", low):
        found.warn("copied-code", rel, no, "GPL-licensed code: copying it puts the program under the GPL — "
                                           "rewrite it or check the licence is compatible")
    m = re.search(r"copyright\s*(?:\(c\)|©)\s*(?:\d{4}(?:\s*[-–,]\s*\d{4})*)?\s*([^\n*/]{2,60})", line, re.I)
    if m and owners and m.group(1).strip().lower() not in owners:
        found.warn("copied-code", rel, no, f"someone else's copyright ({m.group(1).strip()}): check the "
                                           "licence of this code and keep the notice")
    if "all rights reserved" in low:
        found.warn("copied-code", rel, no, "\"All rights reserved\": this code may not be reusable")


# ── Dependencies ─────────────────────────────────────────────────────────────

def licence_verdict(text: str) -> tuple[str, str] | None:
    """(level, why) for a dependency licence, None when it is permissive."""
    t = (text or "").upper()
    if not t.strip() or t.startswith("SEE LICENSE") or t == "UNKNOWN":
        return "warning", "unknown licence: read it before shipping"
    if " OR " in t:                                      # dual licensing: the best option counts
        verdicts = [licence_verdict(part.strip(" ()")) for part in t.split(" OR ")]
        return None if None in verdicts else min(verdicts, key=lambda v: v[0] == "error")
    if re.search(r"AGPL|SSPL|BUSL|BUSINESS SOURCE|COMMONS CLAUSE|ELASTIC LICENSE|NON-?COMMERCIAL|"
                 r"CC-BY-NC|UNLICENSED|PROPRIETARY", t):
        return "error", "forbids or restricts commercial or SaaS use"
    if "LGPL" in t or "LESSER GENERAL" in t:
        return "warning", "weak copyleft: keep it a separate library the user can replace"
    if re.search(r"\bGPL|GENERAL PUBLIC LICENSE|EUPL", t):
        return "warning", "strong copyleft: distributing it puts the whole program under its licence"
    return None


def npm_licence(root: Path, name: str) -> str | None:
    meta = root / "node_modules" / name / "package.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lic = data.get("license") or data.get("licenses") or ""
    if isinstance(lic, dict):
        lic = lic.get("type", "")
    if isinstance(lic, list):
        lic = " OR ".join(str(x.get("type", x) if isinstance(x, dict) else x) for x in lic)
    return str(lic)


def python_licences(root: Path) -> dict[str, str]:
    """Licence of each package installed in the project's own virtual environment."""
    out: dict[str, str] = {}
    for env in (".venv", "venv", "env"):
        for meta in (root / env).glob("**/site-packages/*.dist-info/METADATA"):
            name = lic = ""
            classifiers = []
            for line in (read_text(meta) or "").splitlines():
                if not line.strip():
                    break                                # end of the headers
                field, _, value = line.partition(":")
                value = value.strip()
                if field == "Name":
                    name = value
                elif field in ("License-Expression", "License") and not lic:
                    lic = value
                elif field == "Classifier" and "License ::" in value:
                    classifiers.append(value.split("::")[-1].strip())
            if not name:
                continue
            if not lic or len(lic) > 80:                 # some packages paste the whole licence
                lic = " OR ".join(classifiers)
            out[re.sub(r"[-_.]+", "-", name).lower()] = lic
    return out


def python_requirements(root: Path) -> list[str]:
    names = []
    for req in root.glob("requirements*.txt"):
        for line in (read_text(req) or "").splitlines():
            m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if m and not line.strip().startswith(("#", "-")):
                names.append(m.group(1))
    pyproject = root / "pyproject.toml"
    if tomllib and pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for dep in (data.get("project") or {}).get("dependencies") or []:
            m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", dep)
            if m:
                names.append(m.group(1))
    return names


def check_dependencies(root: Path, credits: dict, found: Findings) -> dict:
    allowed = {k.lower() for k in credits["dependencies"]}
    checked, missing = 0, []
    manifest = root / "package.json"
    if manifest.is_file():
        try:
            deps = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies") or {}
        except ValueError:
            deps = {}
        for name in deps:
            lic = npm_licence(root, name)
            if lic is None:
                missing.append(name)
                continue
            checked += 1
            verdict = licence_verdict(lic)
            if verdict and name.lower() not in allowed:
                found.add(verdict[0], "dependency-licence", "package.json", 0,
                          f"{name} ({lic}): {verdict[1]}")
    py = python_licences(root)
    for name in python_requirements(root):
        norm = re.sub(r"[-_.]+", "-", name).lower()
        if norm not in py:
            missing.append(name)
            continue
        checked += 1
        verdict = licence_verdict(py[norm])
        if verdict and norm not in allowed:
            found.add(verdict[0], "dependency-licence", "requirements", 0,
                      f"{name} ({py[norm]}): {verdict[1]}")
    if missing:
        more = " …" if len(missing) > 8 else ""
        found.warn("dependency-licence", "package.json" if manifest.is_file() else "requirements", 0,
                   f"{len(missing)} dependenc{'y' if len(missing) == 1 else 'ies'} not installed, licence "
                   f"not checked: {', '.join(missing[:8])}{more} — install them and scan again")
    return {"dependencies_checked": checked, "dependencies_unchecked": len(missing)}


# ── The project as a whole ───────────────────────────────────────────────────

def check_project(root: Path, files: list[str], texts: dict[str, str], found: Findings) -> None:
    top = {Path(f).name.upper() for f in files if "/" not in f}
    if not any(n.startswith(("LICENSE", "LICENCE", "COPYING")) for n in top):
        found.warn("licence-file", ".", 0, "no LICENSE file: the code is \"all rights reserved\" — fine "
                                           "for a private project, otherwise choose a licence")
    pages = [f for f in files if Path(f).suffix.lower() in MARKUP_EXT]
    if not pages:
        return
    collecting = [f for f in pages if COLLECTS_DATA.search(texts.get(f, ""))]
    has_privacy = (any(PRIVACY_PATH.search(f) for f in files)
                   or any(PRIVACY_LINK.search(texts.get(f, "")) for f in pages))
    if collecting and not has_privacy:
        found.warn("legal-pages", collecting[0], 0, "this form collects personal data and the site has no "
                                                    "privacy policy (GDPR art. 13): add one and link it "
                                                    "from the form")
    if not any(LEGAL_PAGE.search(f) or LEGAL_PAGE.search(texts.get(f, "")) for f in pages):
        found.warn("legal-pages", pages[0], 0, "no legal notice page (mentions légales, LCEN art. 6): "
                                               "a public site must name its publisher and host")


def copyright_owners(root: Path) -> str:
    """The names in the project's own LICENSE: their copyright lines are not foreign."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"):
        text = read_text(root / name)
        if text:
            return text.lower()
    return ""


def scan(root: Path, skip: list[str]) -> tuple[Findings, dict]:
    found = Findings()
    files = project_files(root, skip)
    credits = load_credits(root, found)
    summary = check_assets(files, credits, found)
    texts: dict[str, str] = {}
    for f in files:
        if Path(f).suffix.lower() in TEXT_EXT and Path(f).name not in SKIP_FILES \
                and not re.search(r"\.min\.(js|css)$|\.map$", f):
            texts[f] = read_text(root / f) or ""
    # A consent manager counts when the code loads one, not when a document names one.
    consent = any(CONSENT_TOOLS.search(t) for f, t in texts.items()
                  if Path(f).suffix.lower() in CODE_EXT or Path(f).name == "package.json")
    owners = copyright_owners(root)
    for f, text in texts.items():
        scan_text(f, text, credits, owners, found, consent)
    summary.update(check_dependencies(root, credits, found))
    check_project(root, files, texts, found)
    summary.update(files=len(files), consent_manager=consent)
    return found, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Licence, copyright and GDPR scan of a project folder.")
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    ap.add_argument("--skip", action="append", default=[], help="a folder never shipped (repeatable)")
    a = ap.parse_args(argv)
    root = Path(a.folder).resolve()
    if not root.is_dir():
        print(f"ERROR   {root} is not a folder")
        return 2
    found, summary = scan(root, a.skip)
    if a.json:
        print(json.dumps({"errors": found.errors, "warnings": found.warnings, "summary": summary},
                         ensure_ascii=False, indent=1))
        return 1 if found.errors else 0
    for f in sorted(found.items, key=lambda f: (f["level"] != "error", f["file"], f["line"])):
        where = f["file"] + (f":{f['line']}" if f["line"] else "")
        print(f"{'ERROR' if f['level'] == 'error' else 'WARN':<7} {where} [{f['rule']}] {f['message']}")
    print(f"{summary['files']} files, {summary['media']} assets ({summary['registered']} in credits.json), "
          f"{summary['dependencies_checked']} dependencies checked — "
          f"{len(found.errors)} error(s), {len(found.warnings)} warning(s)")
    return 1 if found.errors else 0


if __name__ == "__main__":
    sys.exit(main())
