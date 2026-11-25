"""Erkennung, Validierung und Direkt-Import von Blueprints von wohnsinnigvernetzt.de."""

from __future__ import annotations

from dataclasses import dataclass, field
import html as html_lib
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlunparse

import yaml

from .const import ALLOWED_BLUEPRINT_DOMAINS, BLUEPRINT_SUBDIR

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Erkennt vollständige URLs und relative Pfad-URLs auf .yaml / .yml (auch mit Leerzeichen in Quotes)
_QUOTED_YAML_URL_RE = re.compile(
    r"""(?P<q>["'`])(?P<url>(?:https?://|(?:\.\.?/|/|[a-zA-Z0-9_-]+/))[^"'`<>\n\r]+?\.ya?ml(?:\?[^"'`<>\n\r]*)?)(?P=q)""",
    re.IGNORECASE,
)
_BARE_YAML_URL_RE = re.compile(
    r"""(?:https?://[^\s"'`<>()\\]+|(?:\.\.?/|/|[a-zA-Z0-9_-]+/)[^\s"'`<>()\\]+)\.ya?ml(?:\?[^\s"'`<>()\\]*)?""",
    re.IGNORECASE,
)
_MY_HA_RE = re.compile(
    r"""https?://my\.home-assistant\.io/redirect/blueprint_import/\?[^\s"'`<>()]+""",
    re.IGNORECASE,
)

_IGNORED_YAML_FILENAMES = {
    "configuration.yaml",
    "secrets.yaml",
    "automations.yaml",
    "scripts.yaml",
    "scenes.yaml",
    "customize.yaml",
    "groups.yaml",
    "ui-lovelace.yaml",
    "docker-compose.yaml",
    "compose.yaml",
}

_GENERIC_LINK_TEXTS = {
    "yaml-datei im browser öffnen",
    "yaml im browser öffnen",
    "yaml öffnen",
    "kopieren",
    "download",
    "herunterladen",
    "importieren",
    "blueprint importieren",
    "link kopieren",
    "öffnen",
}

_CDN_HOSTS = (
    "cdn.tailwindcss.com",
    "unpkg.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "fonts.googleapis.com",
    "ajax.googleapis.com",
    "code.jquery.com",
    "kit.fontawesome.com",
    "open.spotify.com",
)

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _BlueprintSafeLoader(yaml.SafeLoader):
    """YAML-SafeLoader, der Home-Assistant-Tags wie !input oder !secret toleriert."""


def _ignore_ha_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return f"!{suffix} {loader.construct_scalar(node)}"
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_BlueprintSafeLoader.add_multi_constructor("!", _ignore_ha_tag)


def _is_ignored_filename(url: str) -> bool:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name.lower()
    return name in _IGNORED_YAML_FILENAMES


def normalize_blueprint_url(raw_url: str, base_url: str) -> str:
    """Löst relative Pfade, My-HA-Redirects und GitHub-Blob-URLs zu direkten YAML-URLs auf."""
    url = html_lib.unescape(raw_url).replace("\\/", "/").strip().strip("'\"`")
    if not url:
        return ""

    resolved = urljoin(base_url, url)
    parsed = urlparse(resolved)

    # My Home Assistant Redirect entpacken
    if parsed.netloc.lower() == "my.home-assistant.io":
        qs = parse_qs(parsed.query)
        inner = qs.get("blueprint_url")
        if inner and inner[0]:
            resolved = inner[0].strip()
            parsed = urlparse(resolved)

    # GitHub blob -> raw.githubusercontent.com
    if parsed.netloc.lower() == "github.com" and "/blob/" in parsed.path:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 5 and parts[2] == "blob":
            owner, repo = parts[0], parts[1]
            branch_and_path = "/".join(parts[3:])
            resolved = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch_and_path}"
            parsed = urlparse(resolved)

    if parsed.scheme not in ("http", "https"):
        return ""

    # Eventuelle Leerzeichen oder Sonderzeichen im Pfad sauber URL-kodieren
    safe_path = quote(unquote(parsed.path), safe="/:@-._~!$&'()*+,;=")
    resolved = urlunparse(
        (parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, "")
    )
    if _is_ignored_filename(resolved):
        return ""
    return resolved


def build_safe_filename(url: str, title: str = "") -> str:
    """Erzeugt einen sicheren .yaml-Dateinamen ohne Pfad-Traversal."""
    parsed = urlparse(url)
    raw_name = Path(unquote(parsed.path)).name
    stem = Path(raw_name).stem if raw_name else ""
    if not stem:
        stem = title or "blueprint"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_-").lower()
    if not safe:
        safe = "blueprint"
    return f"{safe[:80]}.yaml"


def _prettify_filename(url: str) -> str:
    parsed = urlparse(url)
    stem = Path(unquote(parsed.path)).stem
    pretty = re.sub(r"[_-]+", " ", stem).strip()
    return pretty.title() if pretty else "Home Assistant Blueprint"


def validate_blueprint_yaml(yaml_text: str) -> tuple[str, str | None]:
    """Prüft, ob der Inhalt ein gültiger HA-Blueprint ist, und gibt (domain, name) zurück."""
    try:
        data = yaml.load(yaml_text, Loader=_BlueprintSafeLoader)
    except yaml.YAMLError as err:
        raise ValueError(f"Ungültiges YAML-Format: {err}") from err

    if not isinstance(data, dict) or not isinstance(data.get("blueprint"), dict):
        raise ValueError(
            "Die heruntergeladene Datei enthält keinen gültigen 'blueprint:'-Abschnitt."
        )

    bp_meta = data["blueprint"]
    bp_domain = str(bp_meta.get("domain", "automation")).strip().lower()
    if bp_domain not in ALLOWED_BLUEPRINT_DOMAINS:
        raise ValueError(
            f"Nicht unterstützte Blueprint-Domain '{bp_domain}' "
            f"(erlaubt: {', '.join(ALLOWED_BLUEPRINT_DOMAINS)})."
        )

    bp_name = bp_meta.get("name")
    return bp_domain, str(bp_name).strip() if bp_name else None


def _extract_urls_from_text_blob(text: str, base_url: str) -> list[tuple[str, int, int]]:
    """Findet alle YAML- und My-HA-Blueprint-URLs inkl. Position in einem Text-/JS-Block."""
    if not text:
        return []
    cleaned = html_lib.unescape(text).replace("\\/", "/")
    raw_hits: list[tuple[int, int, str]] = []

    for m in _MY_HA_RE.finditer(cleaned):
        raw_hits.append((m.start(), m.end(), m.group(0)))
    for m in _QUOTED_YAML_URL_RE.finditer(cleaned):
        raw_hits.append((m.start("url"), m.end("url"), m.group("url")))
    for m in _BARE_YAML_URL_RE.finditer(cleaned):
        raw_hits.append((m.start(), m.end(), m.group(0)))

    raw_hits.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    results: list[tuple[str, int, int]] = []
    seen_spans: list[tuple[int, int]] = []
    for start, end, raw_u in raw_hits:
        if any(s <= start and end <= e for s, e in seen_spans):
            continue
        norm = normalize_blueprint_url(raw_u, base_url)
        if not norm:
            continue
        if not norm.lower().split("?")[0].endswith((".yaml", ".yml")):
            continue
        seen_spans.append((start, end))
        results.append((norm, start, end))
    return results


def _slice_enclosing_js_object(text: str, start: int, end: int) -> str:
    """Extrahiert das umschließende { ... }-JS-Objekt um eine URL-Position."""
    depth = 0
    obj_start = -1
    for i in range(start - 1, max(-1, start - 1200), -1):
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                obj_start = i
                break
            depth -= 1

    if obj_start != -1:
        depth = 0
        for j in range(end, min(len(text), end + 1200)):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                if depth == 0:
                    return text[obj_start : j + 1]
                depth -= 1

    return text[max(0, start - 220) : min(len(text), end + 220)]


def extract_blueprints_from_js_blob(
    blob: str, base_url: str, seen: set[str]
) -> list[dict]:
    """Extrahiert Blueprint-Objekte (Titel, Beschreibung, URL) aus JS/Alpine-Code."""
    found: list[dict] = []
    if not blob:
        return found

    cleaned = html_lib.unescape(blob).replace("\\/", "/")
    hits = _extract_urls_from_text_blob(cleaned, base_url)

    for norm, start, end in hits:
        if norm in seen:
            continue
        seen.add(norm)

        obj_slice = _slice_enclosing_js_object(cleaned, start, end)

        title_match = re.search(
            r"""(?:["']?(?:title|name|titel|heading|label)["']?)\s*:\s*(?P<q>["'`])(?P<val>[^"'`]{2,160})(?P=q)""",
            obj_slice,
            re.IGNORECASE,
        )
        desc_match = re.search(
            r"""(?:["']?(?:description|desc|beschreibung|subtitle|text|info)["']?)\s*:\s*(?P<q>["'`])(?P<val>[^"'`]{4,400})(?P=q)""",
            obj_slice,
            re.IGNORECASE,
        )

        title = (
            title_match.group("val").strip()
            if title_match
            else _prettify_filename(norm)
        )
        description = desc_match.group("val").strip() if desc_match else ""
        fname = build_safe_filename(norm, title)

        found.append(
            {
                "id": fname,
                "filename": fname,
                "title": title[:160],
                "description": description[:350],
                "url": norm,
            }
        )
    return found


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    own_urls: list[str] = field(default_factory=list)
    subtree_urls: set[str] = field(default_factory=set)

    def full_text(self) -> str:
        parts = list(self.texts)
        for child in self.children:
            if child.tag not in ("script", "style", "svg"):
                t = child.full_text()
                if t:
                    parts.append(t)
        return re.sub(r"\s+", " ", " ".join(parts)).strip()


class _BlueprintHTMLTreeParser(HTMLParser):
    """Baut einen kompakten DOM-Baum auf und sammelt alle Blueprint-URLs aus Attributen, Text & Scripts."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.root = _Node(tag="document")
        self._stack: list[_Node] = [self.root]
        self.url_nodes: list[tuple[str, _Node]] = []
        self.js_blobs: list[str] = []
        self.external_scripts: list[str] = []
        self.candidate_subpages: list[str] = []

    def _register_node_url(self, node: _Node, url: str) -> None:
        if url not in node.own_urls:
            node.own_urls.append(url)
            self.url_nodes.append((url, node))
        cur: _Node | None = node
        while cur is not None:
            cur.subtree_urls.add(url)
            cur = cur.parent

    def _inspect_attrs(self, tag: str, attrs_dict: dict[str, str], node: _Node) -> None:
        base_host = urlparse(self.base_url).netloc.lower()

        if tag == "script" and attrs_dict.get("src"):
            script_url = urljoin(self.base_url, attrs_dict["src"].strip())
            s_parsed = urlparse(script_url)
            s_host = s_parsed.netloc.lower()
            if (
                s_parsed.scheme in ("http", "https")
                and s_host == base_host
                and not any(cdn in s_host for cdn in _CDN_HOSTS)
                and script_url not in self.external_scripts
            ):
                self.external_scripts.append(script_url)

        if tag == "a" and attrs_dict.get("href"):
            href_val = attrs_dict["href"].strip()
            if "blueprint" in href_val.lower() and not href_val.startswith("#"):
                sub_url = urljoin(self.base_url, href_val)
                sub_parsed = urlparse(sub_url)
                if (
                    sub_parsed.scheme in ("http", "https")
                    and sub_parsed.netloc.lower() == base_host
                    and not sub_parsed.path.lower().endswith((".yaml", ".yml"))
                    and sub_url != self.base_url
                    and sub_url not in self.candidate_subpages
                ):
                    self.candidate_subpages.append(sub_url)

        # JEDES Attribut (inkl. href, value, onclick, @click, x-on:click, :href, x-data, data-*) prüfen!
        for attr_name, attr_val in attrs_dict.items():
            if not attr_val:
                continue
            lval = attr_val.lower()
            if ".yaml" not in lval and ".yml" not in lval and "blueprint_url=" not in lval:
                continue

            hits = _extract_urls_from_text_blob(attr_val, self.base_url)

            # Enthält ein Attribut mehrere URLs (z. B. Blueprint-Array in x-data) -> als JS-Blob auswerten.
            # Enthält x-data genau EINE URL (wie auf wohnsinnigvernetzt.de pro Karte), am DOM-Node registrieren,
            # damit <h4>-Titel und <p>-Beschreibung direkt aus der Karte gelesen werden!
            if len(hits) > 1:
                self.js_blobs.append(attr_val)
                continue

            if len(hits) == 1:
                self._register_node_url(node, hits[0][0])
            elif attr_name in ("href", "value", "data-url", "data-href", "data-blueprint"):
                norm = normalize_blueprint_url(attr_val, self.base_url)
                if norm and norm.lower().split("?")[0].endswith((".yaml", ".yml")):
                    self._register_node_url(node, norm)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ltag = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        parent = self._stack[-1]
        node = _Node(tag=ltag, attrs=attrs_dict, parent=parent)
        parent.children.append(node)

        self._inspect_attrs(ltag, attrs_dict, node)

        if ltag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        ltag = tag.lower()
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx].tag == ltag:
                del self._stack[idx:]
                break

    def handle_data(self, data: str) -> None:
        if not data:
            return
        cur = self._stack[-1]
        if cur.tag == "script":
            self.js_blobs.append(data)
            return
        if cur.tag == "style":
            return

        stripped = data.strip()
        if not stripped:
            return
        cur.texts.append(stripped)

        ltext = stripped.lower()
        if "http" in ltext and (".yaml" in ltext or ".yml" in ltext or "blueprint_url=" in ltext):
            for norm, _, _ in _extract_urls_from_text_blob(stripped, self.base_url):
                self._register_node_url(cur, norm)


def _find_card_node(node: _Node, url: str) -> _Node:
    """Läuft im DOM nach oben bis zum größten Container, der nur diese eine URL enthält."""
    best = node
    cur = node.parent
    while cur is not None and cur.tag not in ("body", "html", "document"):
        if cur.subtree_urls == {url}:
            best = cur
            cur = cur.parent
        else:
            break
    return best


def _extract_card_metadata(card: _Node, url: str) -> tuple[str, str]:
    """Liest Titel und Beschreibung aus einer Blueprint-Karten-Node."""
    headings: list[str] = []
    paragraphs: list[str] = []
    strongs: list[str] = []
    link_texts: list[str] = []

    def walk(n: _Node) -> None:
        if n.tag in ("script", "style", "svg"):
            return
        if n.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            t = n.full_text()
            if t:
                headings.append(t)
        elif n.tag == "p":
            t = n.full_text()
            if t and t.lower() not in _GENERIC_LINK_TEXTS and not t.startswith("http"):
                paragraphs.append(t)
        elif n.tag in ("strong", "b"):
            t = n.full_text()
            if t and t.lower() not in _GENERIC_LINK_TEXTS:
                strongs.append(t)
        elif n.tag == "a":
            t = n.full_text()
            if t and t.lower() not in _GENERIC_LINK_TEXTS and not t.startswith("http"):
                link_texts.append(t)
        for ch in n.children:
            walk(ch)

    walk(card)

    if headings:
        title = headings[0]
    elif strongs:
        title = strongs[0]
    elif link_texts:
        title = link_texts[0]
    else:
        title = _prettify_filename(url)

    description = ""
    for p in paragraphs:
        if p != title:
            description = p
            break

    return title[:160], description[:350]


def parse_blueprints_catalog_with_hints(
    raw_text: str, base_url: str
) -> tuple[list[dict], list[str], list[str]]:
    """Parst Blueprints aus JSON oder HTML und liefert zusätzlich Script- & Subpage-URLs."""
    stripped = raw_text.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            payload = json.loads(stripped)
            items = (
                payload.get("blueprints", [])
                if isinstance(payload, dict)
                else payload
            )
            if isinstance(items, list):
                results: list[dict] = []
                seen_json: set[str] = set()
                for entry in items:
                    if not isinstance(entry, dict) or not entry.get("url"):
                        continue
                    norm = normalize_blueprint_url(str(entry["url"]), base_url)
                    if not norm or norm in seen_json:
                        continue
                    seen_json.add(norm)
                    title = str(
                        entry.get("title")
                        or entry.get("name")
                        or _prettify_filename(norm)
                    ).strip()
                    desc = str(entry.get("description") or "").strip()
                    fname = build_safe_filename(norm, title)
                    results.append(
                        {
                            "id": fname,
                            "filename": fname,
                            "title": title[:160],
                            "description": desc[:350],
                            "url": norm,
                        }
                    )
                if results:
                    return results, [], []
        except json.JSONDecodeError:
            pass

    parser = _BlueprintHTMLTreeParser(base_url)
    parser.feed(raw_text)

    blueprints: list[dict] = []
    seen_urls: set[str] = set()

    for url, node in parser.url_nodes:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        card = _find_card_node(node, url)
        title, description = _extract_card_metadata(card, url)
        fname = build_safe_filename(url, title)
        blueprints.append(
            {
                "id": fname,
                "filename": fname,
                "title": title,
                "description": description,
                "url": url,
            }
        )

    for blob in parser.js_blobs:
        blueprints.extend(extract_blueprints_from_js_blob(blob, base_url, seen_urls))

    return blueprints, parser.external_scripts, parser.candidate_subpages


def parse_blueprints_catalog(raw_text: str, base_url: str) -> list[dict]:
    """Kompatibilitäts-Wrapper: gibt nur die erkannte Blueprint-Liste zurück."""
    blueprints, _, _ = parse_blueprints_catalog_with_hints(raw_text, base_url)
    return blueprints


def annotate_installed_status(blueprints: list[dict], config_dir: str) -> list[dict]:
    """Prüft lokal im HA-Konfigurationsordner, welche Blueprints installiert sind inkl. Hash."""
    enriched: list[dict] = []
    config_root = Path(config_dir)
    for bp in blueprints:
        fname = bp["filename"]
        installed_domain = None
        local_hash = ""
        for domain in ALLOWED_BLUEPRINT_DOMAINS:
            target = config_root / "blueprints" / domain / BLUEPRINT_SUBDIR / fname
            if target.is_file():
                installed_domain = domain
                local_hash = _read_local_hash(target)
                break
        remote_hash = bp.get("remote_hash", "")
        update_available = bool(
            installed_domain
            and local_hash
            and remote_hash
            and local_hash != remote_hash
        )
        enriched.append(
            {
                **bp,
                "installed": installed_domain is not None,
                "installed_domain": installed_domain or "automation",
                "installed_path": f"{BLUEPRINT_SUBDIR}/{fname}" if installed_domain else "",
                "local_hash": local_hash,
                "remote_hash": remote_hash,
                "update_available": update_available,
            }
        )
    return enriched


def write_blueprint_file(
    config_dir: str, bp_domain: str, filename: str, yaml_text: str
) -> str:
    """Speichert eine validierte Blueprint-YAML-Datei direkt im HA-Blueprints-Ordner."""
    target_dir = Path(config_dir) / "blueprints" / bp_domain / BLUEPRINT_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / filename
    target_file.write_text(yaml_text, encoding="utf-8")
    return f"{BLUEPRINT_SUBDIR}/{filename}"


def compute_yaml_hash(yaml_text: str) -> str:
    """Berechnet einen zeilenumbruch-normalisierten SHA-256-Hash für Update-Vergleiche."""
    normalized = yaml_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _read_local_hash(path: Path) -> str:
    try:
        return compute_yaml_hash(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


# Erkennt numerische Episoden-Infografiken wie '23.jpeg', '18.jpg', '3.png' oder '/pfad/23.jpeg'
_NUMERIC_IMAGE_RE = re.compile(
    r"""(?P<q>["'`])(?P<url>(?:(?:https?://|(?:\.\.?/|/|[a-zA-Z0-9_-]+/)*)?)(?P<num>\d+)\.(?:jpe?g|png)(?:\?[^"'`<>\n\r]*)?)(?P=q)""",
    re.IGNORECASE,
)
_NUMERIC_STEM_RE = re.compile(r"^(\d+)\.(?:jpe?g|png)$", re.IGNORECASE)


def _extract_numeric_episode_from_url(url: str) -> int | None:
    """Gibt die Episodennummer zurück, falls der Dateiname rein numerisch ist (z. B. 23.jpeg -> 23)."""
    parsed = urlparse(url)
    filename = Path(unquote(parsed.path)).name
    match = _NUMERIC_STEM_RE.match(filename)
    if not match:
        return None
    num = int(match.group(1))
    return num if num > 0 else None


def _normalize_image_url(raw_url: str, base_url: str) -> str:
    url = html_lib.unescape(raw_url).replace("\\/", "/").strip().strip("'\"`")
    if not url or url.startswith("data:"):
        return ""
    resolved = urljoin(base_url, url)
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https"):
        return ""
    safe_path = quote(unquote(parsed.path), safe="/:@-._~!$&'()*+,;=")
    return urlunparse(
        (parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, "")
    )


class _InfographicHTMLParser(HTMLParser):
    """Sammelt ausschließlich numerische Episoden-Infografiken (<nummer>.jpg/.jpeg/.png)."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.by_number: dict[int, dict] = {}
        self._in_script = False
        self.js_blobs: list[str] = []

    def _add_candidate(self, raw_url: str) -> None:
        norm = _normalize_image_url(raw_url, self.base_url)
        if not norm:
            return
        ep_num = _extract_numeric_episode_from_url(norm)
        if ep_num is None:
            return
        if ep_num not in self.by_number:
            fname = Path(unquote(urlparse(norm).path)).name
            self.by_number[ep_num] = {
                "episode_number": ep_num,
                "filename": fname,
                "url": norm,
                "title": f"Folge {ep_num} – Infografik",
            }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ltag = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        if ltag == "script":
            self._in_script = True
        if ltag == "img":
            for key in ("src", "data-src", "data-full", "data-image"):
                val = attrs_dict.get(key, "").strip()
                if val and not val.startswith("{"):
                    self._add_candidate(val)
        for attr_name, attr_val in attrs_dict.items():
            if not attr_val:
                continue
            if attr_name in ("x-data", "x-init", "onclick", "@click") and any(
                ext in attr_val.lower() for ext in (".png", ".jpg", ".jpeg")
            ):
                self.js_blobs.append(attr_val)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data:
            self.js_blobs.append(data)


def parse_infographics_from_html(raw_html: str, base_url: str) -> list[dict]:
    """Extrahiert alle numerischen Episoden-Infografiken (z. B. 23.jpeg) absteigend sortiert."""
    parser = _InfographicHTMLParser(base_url)
    parser.feed(raw_html)

    for blob in parser.js_blobs:
        cleaned = html_lib.unescape(blob).replace("\\/", "/")
        for match in _NUMERIC_IMAGE_RE.finditer(cleaned):
            parser._add_candidate(match.group("url"))

    return sorted(
        parser.by_number.values(),
        key=lambda item: item["episode_number"],
        reverse=True,
    )


def match_episode_infographic(
    episode: dict | None, infographics: list[dict]
) -> dict | None:
    """Ordnet jeder Episode exakt das Bild mit derselben Episodennummer zu (z. B. Folge 23 -> 23.jpeg)."""
    if not infographics:
        return None
    if not episode:
        return infographics[0]

    ep_num = episode.get("episode_number")
    if isinstance(ep_num, int) and ep_num > 0:
        for item in infographics:
            if item.get("episode_number") == ep_num:
                return item
        return None

    return infographics[0]
