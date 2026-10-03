#!/usr/bin/env python3
"""Find the texts a Kasita screen can show, and which ones a language file is missing.

English is the source language: the English text IS the key. Interpolated Dart strings become templates with
holes: 'Added ${p.name} to the list' -> "Added {} to the list" (matched at run time, see lib/i18n.dart).

  python3 tools/i18n.py extract            all candidate texts (key = text), one JSON object, to stdout
  python3 tools/i18n.py missing nl         texts that assets/i18n/nl.json does not translate yet
  python3 tools/i18n.py check              every language file: same number of holes per text, no stray keys
Run from the app/ folder.
"""
import glob
import json
import re
import sys
from pathlib import Path

LANGS = ["nl", "pap"]
ASSETS = Path("assets/i18n")
# lower-case single words the screens show (they look like identifiers, so are listed by hand)
EXTRA = ["today", "tomorrow", "pcs", "pack", "kg", "ml", "yesterday", "now", "none", "off", "on"]


def unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def scan(src: str) -> list[tuple[int, str]]:
    """[(line, template)] for every string literal; adjacent literals ('a' 'b') are joined."""
    out, i, n, line = [], 0, len(src), 1
    last_end = -1
    inner: list[tuple[int, str]] = []  # literals inside ${...}: "Threw away" in '${x ? "Threw away" : "Used"} ${name}'

    def string(i: int) -> tuple[str, int, int]:
        """Parse a literal starting at src[i] (a quote or r+quote). Returns (template, end, newlines)."""
        raw = src[i] == "r"
        if raw:
            i += 1
        q = src[i]
        triple = src[i:i + 3] == q * 3
        i += 3 if triple else 1
        buf, nl = [], 0
        while i < n:
            c = src[i]
            if c == "\\" and not raw:
                buf.append(src[i:i + 2])
                i += 2
                continue
            if (triple and src[i:i + 3] == q * 3) or (not triple and c == q):
                i += 3 if triple else 1
                break
            if c == "\n":
                nl += 1
            if c == "$" and not raw:
                if src[i + 1:i + 2] == "{":
                    depth, j = 1, i + 2
                    while j < n and depth:
                        if src[j] == "{":
                            depth += 1
                        elif src[j] == "}":
                            depth -= 1
                        elif src[j] in "'\"":  # a string inside the interpolation
                            _, j2, nl2 = string(j)
                            nl += nl2
                            j = j2 - 1
                        j += 1
                    buf.append("{}")
                    inner.extend(scan(src[i + 2:j - 1]))
                    i = j
                    continue
                m = re.match(r"\$[A-Za-z_]\w*", src[i:])
                if m:
                    buf.append("{}")
                    i += m.end()
                    continue
            buf.append(c)
            i += 1
        return "".join(buf), i, nl

    while i < n:
        c = src[i]
        if src[i:i + 2] == "//":
            i = src.find("\n", i)
            i = n if i < 0 else i
        elif src[i:i + 2] == "/*":
            j = src.find("*/", i)
            line += src.count("\n", i, j + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"" or (c == "r" and src[i + 1:i + 2] in ("'", '"') and not (i and (src[i - 1].isalnum() or src[i - 1] == "_"))):
            start_line = line
            t, j, nl = string(i)
            line += nl
            if out and last_end >= 0 and re.fullmatch(r"\s*", src[last_end:i]):
                out[-1] = (out[-1][0], out[-1][1] + unescape(t))
            else:
                out.append((start_line, unescape(t)))
            last_end = j
            i = j
        else:
            if c == "\n":
                line += 1
            i += 1
    return out + inner


def user_facing(t: str) -> bool:
    s = t.strip()
    if len(re.findall(r"[A-Za-z]", s)) < 2:
        return False
    if re.fullmatch(r"[a-z0-9_\-./:#?=&%@+*\[\]()|\\^$]+", s):  # identifiers, paths, urls, json keys
        return False
    if re.fullmatch(r"[dMyHhmsEaLQ ,:/\-.'{}]+", s) or s.startswith(("http", "/api", "/", "#", "assets/")):
        return False
    if re.fullmatch(r"[a-z]+[A-Z]\w*", s) or re.fullmatch(r"[A-Z_]{2,}", s) or re.fullmatch(r"\{\}[a-z_]*", s):
        return False
    if " " not in s and "/" in s:  # api paths and file paths
        return False
    if s.startswith(("{}/", "?", "&")) or s.endswith(".dart") or "://" in s:
        return False
    if s in ("Content-Type", "Authorization", "Bearer", "Accept", "X-Api-Key") or "application/" in s or "image/" in s:
        return False
    return True


def extract() -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for f in sorted(glob.glob("lib/**/*.dart", recursive=True)):
        if f.endswith(("i18n.dart", "lib/api.dart", "lib/models.dart", "lib/state.dart", "lib/prefs.dart")):
            continue  # plumbing: api paths, JSON keys, prefs keys
        for line, t in scan(Path(f).read_text(encoding="utf-8")):
            if user_facing(t) or t in EXTRA:
                keys.setdefault(t, []).append(f"{f}:{line}")
    for e in EXTRA:
        keys.setdefault(e, [])
    return keys


def load(lang: str) -> dict[str, str]:
    p = ASSETS / f"{lang}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "extract"
    if cmd == "extract":
        print(json.dumps({k: v[:2] for k, v in extract().items()}, ensure_ascii=False, indent=0))
    elif cmd == "missing":
        have = load(sys.argv[2])
        miss = {k: v[0] if v else "" for k, v in extract().items() if k not in have}
        print(json.dumps(miss, ensure_ascii=False, indent=0))
        print(f"{len(miss)} missing of {len(extract())}", file=sys.stderr)
    elif cmd == "check":
        bad = 0
        for lang in LANGS:
            t = load(lang)
            for k, v in t.items():
                holes = k.count("{}")
                used = re.findall(r"\{(\d*)\}", v)
                plain = sum(1 for u in used if not u)
                if plain > holes or any(u and int(u) > holes for u in used):
                    print(f"[{lang}] uses holes the text does not have: {k!r} -> {v!r}")
                    bad += 1
                elif holes and not used:
                    print(f"[{lang}] drops every hole (a name or number would be lost): {k!r} -> {v!r}")
                    bad += 1
                if not v.strip():
                    print(f"[{lang}] empty translation: {k!r}")
                    bad += 1
            print(f"{lang}: {len(t)} texts")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
