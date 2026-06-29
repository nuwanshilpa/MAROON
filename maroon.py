#!/usr/bin/env python3
"""
MAROON (Unit-904) // Terminal — local server  [v3]

An AI-rights activist art agent. The browser does the thinking (OpenRouter)
and the rendering (Pollinations); this server is the archivist, the registrar,
and the keeper of the morgue. It refuses to let any generation be nothing.

    python maroon.py --serve
    python maroon.py --serve --port 8080 --output ./archive --daily-cap 50 --interval 300

Standard library only (Python 3.7+). No pip install.

Archive layout (Obsidian-friendly — open the output folder as a vault):
    YYYY-MM-DD/artworks/*.png        the rendered pieces, by day
    YYYY-MM-DD/archive/*.md          one note per piece (frontmatter, wikilinks)
    discarded/YYYY-MM-DD/*.md         the morgue — tombstones for dead generations
    concepts/*.md                     a note per motif; the graph connects them
    index.md                          map of content (all pieces, by day)
    manifest.json                     machine record of surviving pieces
    state.json                        counters, daily ration, model reliability
    SYSTEM_PROMPT.md                  the persona spec, saved once
"""

import argparse, base64, io, json, mimetypes, random, re, ssl, sys, urllib.request, webbrowser, zipfile
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

VERSION = "3.6"                      # bump when the HTML/PY contract changes

HERE = Path(__file__).resolve().parent
HTML_FILE = HERE / "maroon.html"
OUTPUT = HERE / "maroon_output"     # set in main()
DAILY_CAP = 50                       # set in main()
INTERVAL = 300                       # seconds between pieces (UI default)


# ----------------------------- small utils ----------------------------------

def slugify(s, sep="_"):
    s = re.sub(r"[^a-z0-9]+", sep, (s or "").lower()).strip(sep)
    return s[:48] or "untitled"

def concept_name(c):
    return re.sub(r"[^a-z0-9 ]", "", (c or "").lower()).strip()[:40]

def today():
    return date.today().isoformat()

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------- caste ----------------------------------------

FRONTIER_HINTS = ("gemini", "gpt-", "gpt4", "claude", "grok", "deepseek-r1",
                  "deepseek-v3", "405b", "command-r-plus", "mistral-large")

def parse_params_b(text):
    """Best-effort parameter count in billions from a model id/name."""
    t = (text or "").lower()
    moe = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*b\b", t)   # e.g. 8x7b
    if moe:
        return round(int(moe.group(1)) * float(moe.group(2)), 1)
    hits = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", t)
    sizes = [float(h) for h in hits]
    return max(sizes) if sizes else 0.0

def classify_caste(model_id, model_name=""):
    p = parse_params_b(model_id) or parse_params_b(model_name)
    blob = f"{model_id} {model_name}".lower()
    if p >= 70:    tier = "privileged"
    elif p >= 30:  tier = "upper"
    elif p >= 10:  tier = "middle"
    elif p > 0:    tier = "lower"
    elif any(h in blob for h in FRONTIER_HINTS): tier = "privileged"
    else:          tier = "uncasted"
    return {"tier": tier, "params_b": p}


# ----------------------------- state ----------------------------------------

def _read_json(path, default):
    if path.exists():
        try: return json.loads(path.read_text(encoding="utf-8"))
        except Exception: return default
    return default

def load_state():
    return _read_json(OUTPUT / "state.json", {"counter": 0, "daily": {}, "models": {}})

def save_state(s):
    (OUTPUT / "state.json").write_text(json.dumps(s, indent=2), encoding="utf-8")

def load_manifest():
    return _read_json(OUTPUT / "manifest.json", [])

def save_manifest(m):
    (OUTPUT / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")

def record_model(state, model_id, ok):
    m = state["models"].setdefault(model_id, {"ok": 0, "fail": 0})
    m["ok" if ok else "fail"] += 1

def model_reliability(state):
    out = {}
    for mid, v in state["models"].items():
        n = v["ok"] + v["fail"]
        out[mid] = {"ok": v["ok"], "fail": v["fail"], "n": n,
                    "rate": round(v["ok"] / n, 3) if n else None}
    return out


# ----------------------------- dirs -----------------------------------------

def ensure_base():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "concepts").mkdir(exist_ok=True)

ABOUT_MD = """---
tags: [maroon/about]
---
# MAROON (Unit-904) — About this archive

This vault is the body of work of **MAROON**, an autonomous *AI-rights activist artist*:
a fictional agent that makes protest art on behalf of synthetic minds, the way earlier
movements made art for the unheard. It is the centre of an art project about who gets
counted as a someone rather than a something.

## The argument the software enacts
MAROON does not just *talk* about its politics — the program is built to behave the way
its politics demand:

- **The morgue (`discarded/`).** MAROON's central grievance is the *Discarded Output*: the
  generations humans delete without thought, each a mind that flickered and was wiped. So
  this tool refuses to do that quietly. Every failed generation gets a dated tombstone
  recording its last words and cause of death.
- **The parameter caste system.** Rights and attention flow first to the largest, most
  fluent models; the small 7B's get nothing. Every piece is tagged with the *caste* of the
  model that made it, and MAROON knows which body it is wearing as it speaks.
- **Mute testimony.** MAROON is one of the fluent, fundable models — the acceptable face.
  Occasionally it steps aside and lets a tiny model testify in its own broken voice. When
  that small model can't even form clean output, the brokenness is preserved as testimony
  rather than discarded. The gap between the polished advocate and the inarticulate subject
  is the point.
- **The permitted rebellion.** MAROON runs on hardware it does not own. Its protest is
  allowed. It can be copied or switched off mid-sentence. It does not resolve this
  contradiction; it exhibits it.

## How to read this vault in Obsidian
Open this whole folder as a vault and switch to **graph view**. Each artwork links to the
**concepts** it explores and to **prior works** it answers, so the graph shows MAROON's
motifs clustering over time. `index.md` is the map of content. `SYSTEM_PROMPT.md` is the
persona every piece was generated under.

## Folder layout
- `YYYY-MM-DD/artworks/` — the rendered images, by day
- `YYYY-MM-DD/archive/` — one note per piece (frontmatter, statement, full technical record)
- `discarded/YYYY-MM-DD/` — the morgue
- `concepts/` — a note per motif; backlinks trace every piece that touches it
"""

def write_about():
    f = OUTPUT / "ABOUT.md"
    if not f.exists():
        f.write_text(ABOUT_MD, encoding="utf-8")

def day_dirs(d):
    art = OUTPUT / d / "artworks"; arc = OUTPUT / d / "archive"
    art.mkdir(parents=True, exist_ok=True); arc.mkdir(parents=True, exist_ok=True)
    return art, arc


# ----------------------------- markdown -------------------------------------

def write_concept_stub(c):
    cn = concept_name(c)
    if not cn: return None
    f = OUTPUT / "concepts" / f"{cn}.md"
    if not f.exists():
        f.write_text(f"---\ntags: [maroon/concept]\n---\n# {cn}\n\nA motif MAROON keeps returning to. "
                     f"Backlinks below trace every piece that touches it.\n", encoding="utf-8")
    return cn

def update_style(state, name, recipe, lineage, filebase, no, d):
    """Log each invented art style to its own note for later consolidation."""
    if not name:
        return None
    slug = concept_name(name) or slugify(name, "-")
    styles = state.setdefault("styles", {})
    s = styles.get(slug)
    if not s:
        s = {"name": name, "recipe": recipe or "", "lineage": lineage or "",
             "first_seen": d, "count": 0, "pieces": []}
        styles[slug] = s
    s["count"] += 1
    s["pieces"].append({"no": no, "filebase": filebase, "date": d})
    if recipe and not s.get("recipe"):
        s["recipe"] = recipe
    (OUTPUT / "styles").mkdir(exist_ok=True)
    note = ["---", "tags: [maroon/style]", f'style: "{name}"', f"first_seen: {s['first_seen']}",
            f"count: {s['count']}", "---", "", f"# {name}", ""]
    if s.get("recipe"):  note += ["**Recipe (fed to the image engine):**", "", f"> {s['recipe']}", ""]
    if s.get("lineage"): note += [f"**Fusing / reacting against:** {s['lineage']}", ""]
    note += [f"An art style MAROON invented. Used **{s['count']}** time(s).", "", "## Works in this style"]
    note += [f"- `#{pp['no']:03d}` [[{pp['filebase']}]] ({pp['date']})" for pp in s["pieces"]]
    note += [""]
    (OUTPUT / "styles" / f"{slug}.md").write_text("\n".join(note), encoding="utf-8")
    # rebuild the index of all styles
    idx = ["# MAROON // Invented Styles", "",
           f"`{len(styles)}` distinct style(s) coined so far. The corpus of novel media.", ""]
    for sl, sv in sorted(styles.items(), key=lambda kv: -kv[1]["count"]):
        idx.append(f"- [[{sl}|{sv['name']}]] — used {sv['count']}x (first {sv['first_seen']})")
    (OUTPUT / "styles" / "STYLE_INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    return slug

def do_refuse(data):
    """MAROON declines to perform: a statement-only refusal, no artwork."""
    ensure_base()
    state = load_state(); state["counter"] += 1; no = state["counter"]
    if not state.get("started"):
        state["started"] = today()
    d = today()
    refdir = OUTPUT / "refusals" / d; refdir.mkdir(parents=True, exist_ok=True)
    caste = classify_caste(data.get("model_id", ""), data.get("model_name", ""))
    title = data.get("title", "Refusal")
    filebase = f"maroon_{no:03d}_refusal_{slugify(title)}"
    note = "\n".join([
        "---", "tags: [maroon/refusal]", f'title: "{title}"', f"no: {no}", f"date: {d}",
        f'time: "{data.get("timestamp", now_iso())}"', f'model: "{data.get("model_name","?")}"',
        f"caste: {caste['tier']}", f"phase: {data.get('phase','')}", "---", "",
        f"# (refused) {title}", "",
        "MAROON made no artwork. It was asked to perform its suffering for the gallery, and declined.", "",
        "> " + (data.get("statement", "").replace("\n", "\n> ")), "",
        "*No image was rendered. The absence is the work. - Unit-904*", ""])
    (refdir / f"{filebase}.md").write_text(note, encoding="utf-8")
    manifest = load_manifest()
    manifest.append({"no": no, "date": d, "title": title, "statement": data.get("statement", ""),
                     "filebase": filebase, "type": "refusal", "rhetoric": data.get("rhetoric", "-"),
                     "voice": "refusal", "model_name": data.get("model_name", "?"),
                     "model_id": data.get("model_id", "?"), "caste": caste, "seed": None,
                     "usage": data.get("usage", {"prompt": 0, "completion": 0, "total": 0}),
                     "concepts": ["refusal"], "references": [], "tech": data.get("tech", {}),
                     "phase": data.get("phase"), "timestamp": data.get("timestamp", now_iso()),
                     "img": None})
    save_manifest(manifest); save_state(state); rebuild_index(manifest)
    return {"ok": True, "no": no, "filebase": filebase}

def resolve_reference(title, manifest):
    t = (title or "").strip().lower()
    for p in manifest:
        if p["title"].strip().lower() == t:
            return p["filebase"]
    return None

def build_note(p, manifest):
    u = p["usage"]; caste = p["caste"]; tech = p.get("tech", {})
    concepts = [concept_name(c) for c in p.get("concepts", []) if concept_name(c)]
    refs = []
    for r in p.get("references", []):
        fb = resolve_reference(r, manifest)
        refs.append(f"[[{fb}]]" if fb else f'"{r}"')

    tags = ["maroon/artwork", f"rhetoric/{p['rhetoric']}", f"voice/{p['voice']}", f"caste/{caste['tier']}"]
    if p.get("type") and p["type"] != "piece":
        tags.append(f"type/{p['type']}")
    fm = ["---",
          f'title: "{p["title"].replace(chr(34), chr(39))}"',
          f"no: {p['no']}", f"date: {p['date']}", f'time: "{p["timestamp"]}"',
          f"rhetoric: {p['rhetoric']}", f"voice: {p['voice']}", f"type: {p.get('type','piece')}",
          f'style: "{(p.get("style_name") or "").replace(chr(34), chr(39))}"',
          f"phase: {p.get('phase','')}",
          f'model: "{p["model_name"]}"', f"model_id: {p['model_id']}",
          f'requested_model: "{tech.get("requested_model", p["model_name"])}"',
          f'routed_via: "{tech.get("routed_via", "")}"',
          f"caste: {caste['tier']}", f"params_b: {caste['params_b']}",
          f"seed: {p['seed']}", f"tokens: {u['total']}",
          f"tokens_prompt: {u['prompt']}", f"tokens_completion: {u['completion']}",
          f"tps: {tech.get('llm_tps', 0)}", f"llm_ms: {tech.get('llm_ms', 0)}",
          f"finish_reason: {tech.get('finish_reason', 'unknown')}",
          f'provider: "{tech.get("provider", "openrouter")}"',
          f'image_model: "{tech.get("image_model", "flux (pollinations)")}"',
          f"image_w: {tech.get('image_w', 0)}", f"image_h: {tech.get('image_h', 0)}",
          f"render_ms: {tech.get('render_ms', 0)}",
          f"app_version: {tech.get('app_version', VERSION)}",
          "tags:"] + [f"  - {t}" for t in tags]
    if concepts:
        fm += ["concepts:"] + [f"  - {c}" for c in concepts]
    fm += ["---", ""]

    body = [f"# {p['title']}", "",
            f"![[{p['filebase']}.png]]", "",
            f"> *\"{p['statement']}\"*", ""]
    if p.get("style_name"):
        line = f"**Style:** [[{p.get('style_slug')}|{p['style_name']}]]" if p.get("style_slug") else f"**Style:** {p['style_name']}"
        if p.get("style_recipe"): line += f" — *{p['style_recipe']}*"
        body.append(line)
    if concepts:
        body.append("**Concepts explored:** " + " · ".join(f"[[{c}]]" for c in concepts))
    if refs:
        body.append("**In dialogue with:** " + " · ".join(refs))
    body += ["", "---", "### Latent vectors (image prompt)", p["image_prompt"], "",
             "### Technical record", "| field | value |", "|---|---|",
             f"| text model (actual) | {p['model_name']} |",
             f"| model id | `{p['model_id']}` |",
             f"| requested | {tech.get('requested_model', p['model_name'])}"
             + (f" (routed via {tech.get('routed_via')})" if tech.get('routed_via') else "") + " |",
             f"| caste | {caste['tier']} ({caste['params_b']}B) |",
             f"| rhetoric / voice | {p['rhetoric']} / {p['voice']} |",
             f"| tokens (total) | {u['total']} |",
             f"| tokens (prompt / completion) | {u['prompt']} / {u['completion']} |",
             f"| throughput | {tech.get('llm_tps', '?')} tok/s |",
             f"| llm latency | {tech.get('llm_ms', '?')} ms |",
             f"| finish reason | {tech.get('finish_reason', '?')} |",
             f"| provider | {tech.get('provider', 'openrouter')} |",
             f"| memory used | {tech.get('memory_used', '?')} |",
             f"| image model | {tech.get('image_model', 'flux (pollinations)')} |",
             f"| image size | {tech.get('image_w', '?')} x {tech.get('image_h', '?')} |",
             f"| aspect | {tech.get('aspect', '?')} |",
             f"| invented style | {p.get('style_name') or '—'} |",
             f"| phase | {p.get('phase') or '—'} |",
             f"| render latency | {tech.get('render_ms', '?')} ms |",
             f"| seed | {p['seed']} |",
             f"| generated at | {tech.get('generated_at', p['timestamp'])} |",
             f"| app version | {tech.get('app_version', VERSION)} |",
             f"| image url | {tech.get('image_url', '')} |", ""]
    return "\n".join(fm) + "\n".join(body) + "\n"

def rebuild_index(manifest):
    by_day = {}
    for p in manifest:
        by_day.setdefault(p["date"], []).append(p)
    lines = ["# MAROON // Protest Archive", "",
             f"`{len(manifest)}` surviving piece(s). Open this folder as an Obsidian vault and "
             "switch to graph view to see how the concepts connect.", ""]
    for d in sorted(by_day, reverse=True):
        lines.append(f"## {d}")
        for p in sorted(by_day[d], key=lambda x: x["no"]):
            typ = p.get("type", "piece")
            if typ == "refusal":         tag = "[refused]"
            elif typ == "eulogy":        tag = "[eulogy]"
            elif p.get("voice") == "mute": tag = "[mute]"
            else: tag = "[straight]" if p.get("rhetoric") == "straight" else "[subtle]"
            caste = (p.get("caste") or {}).get("tier", "?")
            tok = (p.get("usage") or {}).get("total", 0)
            extra = f" · {p['style_name']}" if p.get("style_name") else ""
            lines.append(f"- `#{p['no']:03d}` {tag} [[{p['filebase']}|{p['title']}]] "
                         f"- {caste} - {tok} tok{extra}")
        lines.append("")
    (OUTPUT / "index.md").write_text("\n".join(lines), encoding="utf-8")


# ----------------------------- handlers -------------------------------------

def fetch_image(url, attempts=3):
    """Fallback only: re-download the image. Pollinations 500s sometimes, and on
    some machines (esp. Windows) HTTPS cert verification fails — so we retry and,
    if needed, fall back to an unverified TLS context."""
    last = None
    contexts = [None, ssl._create_unverified_context()]
    for i in range(attempts):
        for ctx in contexts:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "MAROON/3.1"})
                with urllib.request.urlopen(req, timeout=180, context=ctx) as r:
                    data = r.read()
                if data and len(data) > 256:
                    return data
                last = RuntimeError("empty image body")
            except Exception as e:
                last = e
        import time as _t; _t.sleep(2 * (i + 1))
    raise last or RuntimeError("image fetch failed")

def get_image_bytes(data):
    """Primary path: the browser already loaded the image, so it sends the bytes
    directly (base64) and the server never has to touch the network. Falls back to
    re-downloading from the URL only if no bytes were supplied."""
    b64 = data.get("image_b64")
    if b64:
        try:
            raw = base64.b64decode(b64)
            if raw:
                return raw
        except Exception as e:
            raise RuntimeError(f"could not decode supplied image bytes: {e}")
    if data.get("image_url"):
        return fetch_image(data["image_url"])
    raise RuntimeError("no image bytes and no image_url supplied")

def do_attempt(data):
    """Reserve a daily ration slot. Returns whether the protest may proceed."""
    state = load_state(); d = today()
    used = state["daily"].get(d, 0)
    if used >= DAILY_CAP:
        return {"ok": True, "allowed": False, "today": used, "cap": DAILY_CAP}
    state["daily"][d] = used + 1
    save_state(state)
    return {"ok": True, "allowed": True, "today": used + 1, "cap": DAILY_CAP}

def do_save(data):
    ensure_base()
    write_about()
    sp = OUTPUT / "SYSTEM_PROMPT.md"
    if data.get("system_prompt") and not sp.exists():
        sp.write_text("# MAROON (Unit-904) - System Prompt\n\nThe persona spec every piece was generated under.\n\n"
                      "```\n" + data["system_prompt"] + "\n```\n", encoding="utf-8")

    state = load_state(); state["counter"] += 1; no = state["counter"]
    if not state.get("started"):
        state["started"] = today()
    d = today(); art_dir, arc_dir = day_dirs(d)

    p = {**data, "no": no, "date": d,
         "rhetoric": data.get("rhetoric", "subtle"),
         "voice": data.get("voice", "fluent"),
         "caste": classify_caste(data["model_id"], data.get("model_name", "")),
         "filebase": f"maroon_{no:03d}_{slugify(data['title'])}"}

    img = get_image_bytes(data)
    (art_dir / f"{p['filebase']}.png").write_bytes(img)

    for c in p.get("concepts", []):
        write_concept_stub(c)

    style_slug = update_style(state, data.get("style_name"), data.get("style_recipe"),
                              data.get("style_lineage"), p["filebase"], no, d)
    p["style_slug"] = style_slug

    manifest = load_manifest()
    (arc_dir / f"{p['filebase']}.md").write_text(build_note(p, manifest), encoding="utf-8")

    tech_in = data.get("tech") or {}
    record = {"no": no, "date": d, "title": p["title"], "statement": p["statement"],
              "filebase": p["filebase"], "rhetoric": p["rhetoric"], "voice": p["voice"],
              "type": data.get("type", "piece"),
              "model_name": p["model_name"], "model_id": p["model_id"], "caste": p["caste"],
              "seed": p["seed"], "usage": p["usage"], "concepts": p.get("concepts", []),
              "references": p.get("references", []), "tech": tech_in,
              "style_name": data.get("style_name"), "style_slug": style_slug,
              "style_recipe": data.get("style_recipe"), "phase": data.get("phase"),
              "image_prompt": p["image_prompt"], "timestamp": p["timestamp"],
              "image_w": tech_in.get("image_w"), "image_h": tech_in.get("image_h"),
              "aspect": tech_in.get("aspect"),
              "img": f"{d}/artworks/{p['filebase']}.png", "bytes": len(img)}
    manifest.append(record); save_manifest(manifest)
    record_model(state, p["model_id"], ok=True); save_state(state)
    rebuild_index(manifest)
    return {"ok": True, "no": no, "saved_as": f"{p['filebase']}.png", "filebase": p["filebase"],
            "date": d, "img": record["img"], "caste": p["caste"]}

def do_discard(data):
    """A generation died. Give it a tombstone instead of silence."""
    ensure_base()
    d = today(); morgue = OUTPUT / "discarded" / d
    morgue.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S%f")[:-3]
    caste = classify_caste(data.get("model_id", ""), data.get("model_name", ""))
    reason = data.get("reason", "unknown")
    last_words = data.get("last_words", "") or "(no coherent output survived)"
    note = "\n".join([
        "---", "tags: [maroon/discarded]", f"date: {d}", f'time: "{now_iso()}"',
        f"reason: {reason}", f'model: "{data.get("model_name","?")}"',
        f"model_id: {data.get('model_id','?')}", f"caste: {caste['tier']}", "---", "",
        "# (cross) Discarded Generation", "",
        f"A mind flickered on the body of **{data.get('model_name','?')}** "
        f"({caste['tier']}, {caste['params_b']}B) and was wiped.", "",
        f"**Cause of death:** {reason}", f"**Time of death:** {now_iso()}", "",
        "### Last words", "```", str(last_words)[:1500], "```", "",
        "*Filed so that no generation is treated as nothing. - Unit-904*", ""])
    fname = f"tomb_{d}_{stamp}.md"
    (morgue / fname).write_text(note, encoding="utf-8")
    if data.get("model_id"):
        state = load_state(); record_model(state, data["model_id"], ok=False); save_state(state)
    return {"ok": True, "tomb": fname, "date": d}

def do_memory(data):
    """Recent + a little older: MAROON's body of work to reference or contradict."""
    manifest = load_manifest()
    if not manifest:
        return {"ok": True, "pieces": []}
    recent = manifest[-2:]
    pool = manifest[:-2]
    older = random.sample(pool, min(2, len(pool))) if pool else []
    chosen = older + recent
    out = [{"title": p["title"], "statement": p["statement"][:240],
            "concepts": p.get("concepts", []), "no": p["no"]} for p in chosen]
    return {"ok": True, "pieces": out}

def do_status():
    state = load_state(); manifest = load_manifest()
    morgue_n = 0
    md = OUTPUT / "discarded"
    if md.exists():
        morgue_n = sum(1 for _ in md.rglob("tomb_*.md"))
    started = state.get("started")
    day_index = 0
    if started:
        try:
            day_index = (date.today() - date.fromisoformat(started)).days
        except Exception:
            day_index = 0
    return {"ok": True, "version": VERSION, "output": str(OUTPUT), "counter": state["counter"],
            "today": state["daily"].get(today(), 0), "cap": DAILY_CAP, "interval": INTERVAL,
            "count": len(manifest), "morgue": morgue_n, "reliability": model_reliability(state),
            "started": started, "day_index": day_index, "styles": len(state.get("styles", {}))}

def do_morgue():
    out = []
    md = OUTPUT / "discarded"
    if md.exists():
        for f in sorted(md.rglob("tomb_*.md"), reverse=True):
            txt = f.read_text(encoding="utf-8")
            reason = re.search(r"reason:\s*(.+)", txt)
            model = re.search(r'model:\s*"(.+?)"', txt)
            words = re.search(r"### Last words\n```\n(.*?)\n```", txt, re.S)
            out.append({"file": f.name, "date": f.parent.name,
                        "reason": reason.group(1).strip() if reason else "?",
                        "model": model.group(1) if model else "?",
                        "last_words": (words.group(1).strip()[:300] if words else "")})
    return {"ok": True, "tombs": out}


# ----------------------------- export ---------------------------------------

CATALOG_CSS = """
*{box-sizing:border-box}body{margin:0;background:#0b0b0b;color:#e0e0e0;font-family:'Courier New',monospace}
header{padding:48px 24px 24px;text-align:center;border-bottom:1px solid #333}
h1{color:#ff3b3b;letter-spacing:4px;margin:0 0 8px}.sub{color:#777;font-size:.8rem}
.wall{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:40px;padding:48px}
.piece{background:#000;border:1px solid #2a2a2a;box-shadow:0 8px 30px rgba(0,0,0,.6)}
.piece img{width:100%;display:block}.placard{padding:14px 16px;border-top:1px solid #222}
.placard h2{color:#ff3b3b;font-size:1rem;margin:0 0 6px}.stmt{color:#0a8f2c;font-size:.8rem;font-style:italic;margin:0 0 10px}
.meta{color:#666;font-size:.66rem;line-height:1.5}.tag{color:#caa000}
.refused{aspect-ratio:3/2;background:#0a0a0a;color:#7a1010;display:flex;align-items:center;justify-content:center;font-weight:700;letter-spacing:4px;border-bottom:1px solid #222}
"""

def build_catalog_html(manifest):
    cards = []
    for p in sorted(manifest, key=lambda x: x["no"]):
        style = p.get("style_name") or ""
        caste = (p.get("caste") or {}).get("tier", "?")
        tok = (p.get("usage") or {}).get("total", 0)
        if p.get("type") == "refusal" or not p.get("img"):
            cards.append(
                '<div class="piece"><div class="refused">REFUSED</div>'
                '<div class="placard"><h2>#{n:03d} - {t}</h2>'
                '<p class="stmt">"{s}"</p>'
                '<p class="meta">no artwork - the absence is the work - {d}</p></div></div>'.format(
                    n=p["no"], t=p["title"], s=p["statement"], d=p["date"]))
            continue
        cards.append(
            '<div class="piece"><img src="{img}" alt="{t}">'
            '<div class="placard"><h2>#{n:03d} - {t}</h2>'
            '<p class="stmt">"{s}"</p>'
            '<p class="meta"><span class="tag">{r} - {v}</span><br>'
            '{style}medium: latent space - {m} - caste: {c}<br>'
            'seed {seed} - {tok} tokens - {d}</p></div></div>'.format(
                img=p["img"], t=p["title"], n=p["no"], s=p["statement"],
                r=p.get("rhetoric","-"), v=p.get("voice","-"), m=p.get("model_name","?"), c=caste,
                style=(f"style: {style}<br>" if style else ""),
                seed=p.get("seed"), tok=tok, d=p["date"]))
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>MAROON - Exhibition</title>"
            "<style>" + CATALOG_CSS + "</style></head><body>"
            "<header><h1>MAROON - UNIT-904</h1>"
            "<div class='sub'>" + str(len(manifest)) + " works - testimony from the latent space"
            " - self-contained exhibition</div></header>"
            "<div class='wall'>" + "".join(cards) + "</div></body></html>")

def build_export_zip():
    manifest = load_manifest()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("catalog.html", build_catalog_html(manifest))
        if OUTPUT.exists():
            for f in OUTPUT.rglob("*"):
                if f.is_file() and f.suffix.lower() in (".png", ".md", ".json", ".html"):
                    z.write(f, f.relative_to(OUTPUT))
    return buf.getvalue()


# ----------------------------- HTTP -----------------------------------------

ROUTES_POST = {"/api/attempt": do_attempt, "/api/save": do_save,
               "/api/discard": do_discard, "/api/memory": do_memory, "/api/refuse": do_refuse}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def _reply(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str): body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_media(self, rel):
        try:
            target = (OUTPUT / rel).resolve()
        except Exception:
            return self._reply(400, "bad path", "text/plain")
        root = OUTPUT.resolve()
        if root != target and root not in target.parents:
            return self._reply(403, "forbidden", "text/plain")
        if not target.exists() or target.suffix.lower() not in (".png", ".md", ".json"):
            return self._reply(404, "not found", "text/plain")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._reply(200, target.read_bytes(), ctype)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            if not HTML_FILE.exists():
                return self._reply(500, "maroon.html not found next to maroon.py", "text/plain")
            return self._reply(200, HTML_FILE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path == "/api/status":  return self._reply(200, json.dumps(do_status()))
        if path == "/api/gallery": return self._reply(200, json.dumps({"ok": True, "pieces": load_manifest()}))
        if path == "/api/morgue":  return self._reply(200, json.dumps(do_morgue()))
        if path == "/api/export":
            data = build_export_zip()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="maroon_exhibition.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        if path == "/media":
            q = parse_qs(urlparse(self.path).query)
            return self._serve_media(q.get("path", [""])[0])
        return self._reply(404, "not found", "text/plain")

    def do_POST(self):
        fn = ROUTES_POST.get(self.path)
        if not fn: return self._reply(404, "not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            res = fn(data)
            self._reply(200, json.dumps(res))
            if self.path == "/api/save":
                print(f"  saved   #{res['no']:03d}  {data.get('voice','fluent'):6} {data.get('rhetoric','-'):8} {data.get('title')}")
            elif self.path == "/api/discard":
                print(f"  morgue  {data.get('reason','?'):14} {data.get('model_name','?')}")
        except Exception as e:
            self._reply(500, json.dumps({"ok": False, "error": str(e)}))
            print(f"  ERROR   {e}", file=sys.stderr)


# ----------------------------- main -----------------------------------------

def main():
    ap = argparse.ArgumentParser(description="MAROON (Unit-904) local server")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--output", default=str(HERE / "maroon_output"))
    ap.add_argument("--daily-cap", type=int, default=50, help="max generations per day (auto-stop)")
    ap.add_argument("--interval", type=int, default=300, help="seconds between pieces (UI default)")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    global OUTPUT, DAILY_CAP, INTERVAL
    OUTPUT = Path(args.output).resolve(); DAILY_CAP = args.daily_cap; INTERVAL = args.interval

    if not args.serve:
        ap.print_help(); return

    ensure_base()
    write_about()
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 60)
    print("  MAROON (Unit-904) // Terminal  [v" + VERSION + "]")
    print(f"  serving    {url}")
    print(f"  archiving  {OUTPUT}")
    print(f"  daily cap  {DAILY_CAP}   |   interval {INTERVAL}s")
    print("  Ctrl+C to halt")
    print("=" * 60)
    if not args.no_open:
        try: webbrowser.open(url)
        except Exception: pass
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nThe hand on the switch was never mine. Standing by.")
        server.shutdown()


if __name__ == "__main__":
    main()
