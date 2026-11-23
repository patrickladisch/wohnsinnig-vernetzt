"""Erkennung, Validierung und Direkt-Import von Blueprints von wohnsinnigvernetzt.de."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import yaml

from .const import ALLOWED_BLUEPRINT_DOMAINS, BLUEPRINT_SUBDIR

_YAML_URL_RE = re.compile(
    r"""(?:https?://[^\s"'<>()]+|(?:\./|/|[a-zA-Z0-9_-]+/)[^\s"'<>()]+)\.ya?ml(?:\?[^\s"'<>()]*)?""",
    re.IGNORECASE,
)

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


def normalize_blueprint_url(raw_url: str, base_url: str) -> str:
    """Löst relative Pfade, My-HA-Redirects und GitHub-Blob-URLs zu direkten YAML-URLs auf."""
    url = raw_url.strip().strip("'\"")
    if not url:
        return ""

    resolved = urljoin(base_url, url)
    parsed = urlparse(resolved)

    if parsed.netloc.lower() == "my.home-assistant.io":
        qs = parse_qs(parsed.query)
        inner = qs.get("blueprint_url")
        if inner and inner[0]:
            resolved = inner[0].strip()
            parsed = urlparse(resolved)

    if parsed.netloc.lower() == "github.com" and "/blob/" in parsed.path:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 5 and parts[2] == "blob":
            owner, repo = parts[0], parts[1]
            branch_and_path = "/".join(parts[3:])
            resolved = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch_and_path}"
            parsed = urlparse(resolved)

    if parsed.scheme not in ("http", "https"):
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
    """Baut einen kompakten DOM-Baum auf und sammelt alle YAML-Blueprint-URLs."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.root = _Node(tag="document")
        self._stack: list[_Node] = [self.root]
        self.url_nodes: list[tuple[str, _Node]] = []
        self.script_blocks: list[str] = []

    def _extract_urls_from_attrs(self, attrs_dict: dict[str, str]) -> list[str]:
        found: list[str] = []
        for attr_name, attr_val in attrs_dict.items():
            if not attr_val:
                continue
            lname = attr_name.lower()
            if lname in (
                "href", "data-url", "data-blueprint", "data-copy",
                "data-link", "data-href", "value",
            ):
                val = attr_val.strip()
                if ".yaml" in val.lower() or ".yml" in val.lower() or "blueprint_url=" in val.lower():
                    norm = normalize_blueprint_url(val, self.base_url)
                    if norm and norm.lower().split("?")[0].endswith((".yaml", ".yml")):
                        found.append(norm)
            elif lname == "onclick" or lname.startswith("data-"):
                for match in _YAML_URL_RE.findall(attr_val):
                    norm = normalize_blueprint_url(match, self.base_url)
                    if norm:
                        found.append(norm)
        return found

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ltag = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        parent = self._stack[-1]
        node = _Node(tag=ltag, attrs=attrs_dict, parent=parent)
        parent.children.append(node)

        urls = self._extract_urls_from_attrs(attrs_dict)
        for u in urls:
            if u not in node.own_urls:
                node.own_urls.append(u)
                self.url_nodes.append((u, node))
            cur: _Node | None = node
            while cur is not None:
                cur.subtree_urls.add(u)
                cur = cur.parent

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
            self.script_blocks.append(data)
        elif cur.tag != "style":
            stripped = data.strip()
            if stripped:
                cur.texts.append(stripped)


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
            if t and t.lower() not in _GENERIC_LINK_TEXTS:
                paragraphs.append(t)
        elif n.tag in ("strong", "b"):
            t = n.full_text()
            if t and t.lower() not in _GENERIC_LINK_TEXTS:
                strongs.append(t)
        elif n.tag == "a":
            t = n.full_text()
            if t and t.lower() not in _GENERIC_LINK_TEXTS:
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


def _extract_from_scripts(scripts: list[str], base_url: str, seen: set[str]) -> list[dict]:
    """Fallback: findet Blueprint-URLs in JS-Arrays/Objekten innerhalb von <script>-Blöcken."""
    found: list[dict] = []
    joined = "\n".join(scripts)
    if not joined:
        return found

    for match in _YAML_URL_RE.finditer(joined):
        raw_url = match.group(0)
        norm = normalize_blueprint_url(raw_url, base_url)
        if not norm or norm in seen:
            continue
        seen.add(norm)

        start = max(0, match.start() - 350)
        end = min(len(joined), match.end() + 250)
        window = joined[start:end]

        title_match = re.search(
            r"""(?:title|name)\s*[:=]\s*["']([^"']{3,120})["']""",
            window,
            re.IGNORECASE,
        )
        desc_match = re.search(
            r"""(?:description|desc|text)\s*[:=]\s*["']([^"']{5,350})["']""",
            window,
            re.IGNORECASE,
        )

        title = title_match.group(1).strip() if title_match else _prettify_filename(norm)
        description = desc_match.group(1).strip() if desc_match else ""
        fname = build_safe_filename(norm, title)

        found.append(
            {
                "id": fname,
                "filename": fname,
                "title": title,
                "description": description,
                "url": norm,
            }
        )
    return found


def parse_blueprints_catalog(raw_text: str, base_url: str) -> list[dict]:
    """Parst Blueprints entweder aus JSON-Index oder aus einer HTML-Webseite."""
    stripped = raw_text.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            payload = json.loads(stripped)
            items = payload.get("blueprints", []) if isinstance(payload, dict) else payload
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
                    title = str(entry.get("title") or entry.get("name") or _prettify_filename(norm)).strip()
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
                    return results
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

    blueprints.extend(_extract_from_scripts(parser.script_blocks, base_url, seen_urls))
    return blueprints


def annotate_installed_status(blueprints: list[dict], config_dir: str) -> list[dict]:
    """Prüft lokal im HA-Konfigurationsordner, welche Blueprints bereits importiert sind."""
    enriched: list[dict] = []
    config_root = Path(config_dir)
    for bp in blueprints:
        fname = bp["filename"]
        installed_domain = None
        for domain in ALLOWED_BLUEPRINT_DOMAINS:
            target = config_root / "blueprints" / domain / BLUEPRINT_SUBDIR / fname
            if target.is_file():
                installed_domain = domain
                break
        enriched.append(
            {
                **bp,
                "installed": installed_domain is not None,
                "installed_domain": installed_domain or "automation",
                "installed_path": f"{BLUEPRINT_SUBDIR}/{fname}" if installed_domain else "",
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
