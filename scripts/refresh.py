"""Builds the live profile cards from GitHub data. Run daily by .github/workflows/profile.yml.

Writes to $DIST (default ./dist):
  card-<repo>-<theme>.svg   featured cards with screenshot and live stars
  mini-<repo>-<theme>.svg   compact cards for the rest
  stats-<theme>.svg         stars, contributions, followers, projects, languages
Env: GITHUB_TOKEN, GH_USER (default yappologistic)
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import THEMES, esc, measure, style, svg, wrap, write  # noqa: E402

USER = os.environ.get("GH_USER", "yappologistic")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
DIST = Path(os.environ.get("DIST", Path(__file__).resolve().parent.parent / "dist"))

FEATURED = [
    ("Spun", "main", "assets/screenshots/spun-vinyl.png", .30,
     "A music player that spins your album art on a CD, vinyl, cassette or recorder.", ["C++", "Qt Quick", "Linux"]),
    ("Sung", "main", "assets/readme-now-playing.png", .45,
     "A Material 3 player for YouTube Music, local files and your music server.", ["C++", "Qt Quick", "Linux"]),
    ("CUI", "master", "docs/images/showcase/dashboard-dark.png", .20,
     "Native UI components for C. About 150 of them, one C99 codebase, ~250 KB.", ["C99", "Win", "macOS", "Linux"]),
    ("Maia", "main", "docs/maia.webp", .35,
     "A keyboard-first file manager. One GPU-drawn binary under 8 MB.", ["Rust", "egui", "Linux"]),
    ("Cohort", "main", "assets/screenshots/cohort.webp", .40,
     "Power, battery, fan curve and keyboard settings for Lenovo Legion laptops.", ["C++", "Qt Quick", "Linux"]),
    ("Ava", "main", "docs/ava-hero.png", (.2, 0, .8, .5),
     "A live-activity island for Windows 11, with optional Dwindle tiling.", ["C++20", "Qt Quick", "Win32"]),
]

MORE = [
    ("Nala", "A desktop companion for Hyprland that follows your cursor and changes shape.", "C++ · Qt Quick"),
    ("Orbit", "A rotary app launcher for Hyprland. Your favourites, a turn away.", "C++ · Qt Quick"),
    ("Wineel", "A radial Alt+Tab replacement for Windows 10 and 11.", "C# · WPF"),
    ("winotch", "A notch overlay for Windows: media, notifications, agenda, system health.", "C# · WPF"),
    ("FACT3", "A desktop control surface for coding agents like Claude Code and Codex.", "TypeScript · Electron"),
    ("Sprinkle-CLI", "A multi-provider AI coding agent for the terminal.", "Rust · TUI"),
    ("focus-friendly", "A Codex plugin that makes dense information easier to follow.", "Python · Codex"),
    ("Unmuze", "A local desktop app for saving permitted YouTube and SoundCloud media.", "TypeScript"),
    ("e-gurl-community-cpp-qt-qml-roadmap", "A free zero-to-capstone roadmap for modern C++23, Qt 6 and QML.", "Learning"),
    ("CSharp-Tutor", "Codex skills that teach and review C#, backed by the official docs.", "C# · Codex"),
]
DISPLAY_NAME = {"winotch": "Winotch", "e-gurl-community-cpp-qt-qml-roadmap": "C++ / Qt roadmap",
                "CSharp-Tutor": "C# Tutor", "FACT3": "FACT3 Code", "Sprinkle-CLI": "Sprinkle CLI"}

# Large rebranded forks would drown out the code written here, and markup isn't a language you write apps in.
LANG_SKIP_REPOS = {"FACT3", "Sprinkle-CLI", "ZethCode", "scaling-spork-multiplatform"}
LANG_SKIP = {"MDX", "HTML", "CSS", "SCSS", "Makefile", "Dockerfile", "Shell", "PowerShell", "Batchfile", "Nix", "Inno Setup"}

STAR = "M7 1.2l1.75 3.55 3.92.57-2.84 2.76.67 3.9L7 10.13 3.5 11.98l.67-3.9L1.33 5.32l3.92-.57z"


def api(url: str, body: dict | None = None):
    req = urllib.request.Request(
        url if url.startswith("http") else f"https://api.github.com{url}",
        data=json.dumps(body).encode() if body else None,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "profile-refresh",
                 **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "profile-refresh"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def collect() -> dict:
    user = api(f"/users/{USER}")
    repos, page = [], 1
    while True:
        batch = api(f"/users/{USER}/repos?per_page=100&page={page}&type=owner")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    own = [r for r in repos if not r["fork"] and not r["archived"] and r["name"] != USER]
    langs: dict[str, int] = {}
    for r in own:
        if r["name"] in LANG_SKIP_REPOS:
            continue
        for k, v in api(f"/repos/{USER}/{r['name']}/languages").items():
            if k not in LANG_SKIP:
                langs[k] = langs.get(k, 0) + v
    contrib = None
    if TOKEN:
        q = {"query": f'{{user(login:"{USER}"){{contributionsCollection{{contributionCalendar{{totalContributions}}}}}}}}'}
        contrib = api("https://api.github.com/graphql", q)["data"]["user"]["contributionsCollection"][
            "contributionCalendar"]["totalContributions"]
    return {"stars": {r["name"]: r["stargazers_count"] for r in own},
            "total_stars": sum(r["stargazers_count"] for r in own),
            "followers": user["followers"], "repos": len(own), "contrib": contrib, "langs": langs}


def fmt(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def cover(data: bytes, w: int, h: int, focus_y) -> str:
    """Crop-to-fill. focus_y is a vertical anchor (0 top, 1 bottom) or a crop box in fractions."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if isinstance(focus_y, tuple):
        a, b, c2, d2 = focus_y
        im = im.crop((int(a * im.width), int(b * im.height), int(c2 * im.width), int(d2 * im.height)))
        focus_y = 0.0
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    left = (im.width - w) // 2
    top = int((im.height - h) * focus_y)
    im = im.crop((left, top, left + w, top + h))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    return base64.b64encode(buf.getvalue()).decode()


def stars_svg(c: dict, n: int, right: float, y: float) -> tuple[str, str]:
    label = fmt(n)
    tw = measure("sans", label, 13)
    x = right - tw
    return (f'<path transform="translate({x - 19:.1f} {y - 11.5})" d="{STAR}" fill="none" stroke="{c["text3"]}" '
            f'stroke-width="1.2" stroke-linejoin="round"/>'
            f'<text x="{right}" y="{y}" text-anchor="end" class="s" font-size="13" fill="{c["text2"]}">{label}</text>', label)


def card(t: str, name: str, img_b64: str, desc: str, chips: list[str], n: int) -> str:
    c = THEMES[t]
    W, H = 432, 376
    iw, ih = W - 16, 234
    lines = wrap("sans", desc, 13.5, W - 40)[:2]
    st, label = stars_svg(c, n, W - 20, 276)
    chip_svg, cx = [], 20
    for ch in chips:
        cw = measure("mono", ch, 11) + 18
        chip_svg.append(f'<rect x="{cx:.1f}" y="342" width="{cw:.1f}" height="22" rx="11" fill="none" stroke="{c["border"]}"/>'
                        f'<text x="{cx + cw / 2:.1f}" y="356.5" text-anchor="middle" class="m" font-size="11" fill="{c["text3"]}">{esc(ch)}</text>')
        cx += cw + 6
    used = {"display": name, "sans": desc + label, "mono": "".join(chips)}
    body = f"""<defs>{style(used)}
<clipPath id="f"><rect width="{W}" height="{H}" rx="18"/></clipPath>
<clipPath id="i"><rect x="8" y="8" width="{iw}" height="{ih}" rx="12"/></clipPath></defs>
<g clip-path="url(#f)">
<rect width="{W}" height="{H}" fill="{c['surface']}"/>
<rect x="8" y="8" width="{iw}" height="{ih}" rx="12" fill="{c['bezel']}"/>
<image class="fadein" clip-path="url(#i)" x="8" y="8" width="{iw}" height="{ih}" preserveAspectRatio="xMidYMid slice" href="data:image/jpeg;base64,{img_b64}"/>
<rect x="8.5" y="8.5" width="{iw - 1}" height="{ih - 1}" rx="11.5" fill="none" stroke="{c['fg']}" stroke-opacity=".06"/>
<text x="20" y="278" class="d rise" font-size="19" letter-spacing="-.4" fill="{c['fg']}">{esc(name)}</text>
<g class="rise">{st}</g>
{''.join(f'<text x="20" y="{304 + i * 20}" class="s rise" style="animation-delay:.08s" font-size="13.5" fill="{c["text2"]}">{esc(l)}</text>' for i, l in enumerate(lines))}
<g class="rise" style="animation-delay:.14s">{''.join(chip_svg)}</g>
</g>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="17.5" fill="none" stroke="{c['border']}"/>"""
    return svg(W, H, f"{name}: {desc} {label} stars", body)


def mini(t: str, name: str, desc: str, meta: str, n: int) -> str:
    c = THEMES[t]
    W, H = 432, 128
    lines = wrap("sans", desc, 13.5, W - 40)[:2]
    st, label = stars_svg(c, n, W - 20, 36)
    used = {"display": name, "sans": desc + label, "mono": meta}
    body = f"""<defs>{style(used)}</defs>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="14" fill="{c['surface']}" stroke="{c['border']}"/>
<text x="20" y="37" class="d rise" font-size="16" letter-spacing="-.3" fill="{c['fg']}">{esc(name)}</text>
<g class="rise">{st}</g>
{''.join(f'<text x="20" y="{62 + i * 19}" class="s rise" style="animation-delay:.06s" font-size="13.5" fill="{c["text2"]}">{esc(l)}</text>' for i, l in enumerate(lines))}
<text x="20" y="{H - 18}" class="m rise" style="animation-delay:.1s" font-size="11" fill="{c['text3']}">{esc(meta)}</text>"""
    return svg(W, H, f"{name}: {desc}", body)


ICONS = {
    "star": STAR,
    "commit": "M1 7h3.2M9.8 7H13M7 4.6a2.4 2.4 0 1 0 0 4.8a2.4 2.4 0 1 0 0-4.8z",
    "users": "M5 6.4a2.3 2.3 0 1 0 0-4.6a2.3 2.3 0 1 0 0 4.6zM1 12.2c0-2.2 1.8-3.6 4-3.6s4 1.4 4 3.6M9.6 1.9a2.3 2.3 0 0 1 0 4.4M10.8 8.8c1.3.4 2.2 1.6 2.2 3.4",
    "box": "M7 1.2l5.3 3v5.6L7 12.8 1.7 9.8V4.2zM1.7 4.2L7 7.2l5.3-3M7 7.2v5.6",
}


def stats(t: str, d: dict) -> str:
    c = THEMES[t]
    W, gap = 880, 12
    mh = 104
    metrics = [("star", "Stars earned", fmt(d["total_stars"])),
               ("commit", "Contributions this year", fmt(d["contrib"])),
               ("users", "Followers", fmt(d["followers"])),
               ("box", "Public projects", str(d["repos"]))]
    mw = (W - gap * 3) / 4
    parts = []
    for i, (ic, label, val) in enumerate(metrics):
        x = i * (mw + gap)
        parts.append(
            f'<g class="rise" style="animation-delay:{i * 0.06:.2f}s">'
            f'<rect x="{x + .5:.1f}" y=".5" width="{mw - 1:.1f}" height="{mh - 1}" rx="14" fill="{c["surface"]}" stroke="{c["border"]}"/>'
            f'<path transform="translate({x + 18:.1f} 19)" d="{ICONS[ic]}" fill="none" stroke="{c["text2"]}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<text x="{x + 40:.1f}" y="30.5" class="s" font-size="13" fill="{c["text2"]}">{esc(label)}</text>'
            f'<text x="{x + 17:.1f}" y="80" class="d" font-size="34" letter-spacing="-1.1" fill="{c["fg"]}">{esc(val)}</text>'
            f'</g>')

    total = sum(d["langs"].values()) or 1
    top = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:5]
    other = total - sum(v for _, v in top)
    if other > 0:
        top.append(("Other", other))
    palette = [c["red"], c["gold"], c["fg"], c["text3"], c["strong"], c["border"]]
    ly, lh = mh + gap, 132
    today = dt.date.today().strftime("%-d %B %Y")
    parts.append(
        f'<g class="rise" style="animation-delay:.25s">'
        f'<rect x=".5" y="{ly + .5}" width="{W - 1}" height="{lh - 1}" rx="14" fill="{c["surface"]}" stroke="{c["border"]}"/>'
        f'<text x="20" y="{ly + 34}" class="d" font-size="15" fill="{c["fg"]}">Languages</text>'
        f'<text x="20" y="{ly + 54}" class="s" font-size="13" fill="{c["text2"]}">By bytes of code across my public projects</text>'
        f'<text x="{W - 20}" y="{ly + 34}" text-anchor="end" class="s" font-size="13" fill="{c["text3"]}">Updated {today}</text></g>')
    bx, bw, by = 20, W - 40, ly + 74
    segs, x = [], bx
    for i, (k, v) in enumerate(top):
        w = bw * v / total
        segs.append(f'<rect x="{x:.1f}" y="{by}" width="{max(w - 2, 1):.1f}" height="8" fill="{palette[i]}"/>')
        x += w
    parts.append(f'<clipPath id="bar"><rect x="{bx}" y="{by}" width="{bw}" height="8" rx="4"/></clipPath>'
                 f'<g clip-path="url(#bar)"><g class="grow" style="animation-delay:.4s">{"".join(segs)}</g></g>')
    lx = bx
    legend = ""
    for i, (k, v) in enumerate(top):
        pct = f"{v / total * 100:.1f}%"
        parts.append(f'<g class="rise" style="animation-delay:{0.5 + i * 0.04:.2f}s">'
                     f'<circle cx="{lx + 4}" cy="{by + 31}" r="4" fill="{palette[i]}"/>'
                     f'<text x="{lx + 14}" y="{by + 35.5}" class="s" font-size="13" fill="{c["fg"]}">{esc(k)} '
                     f'<tspan fill="{c["text3"]}">{pct}</tspan></text></g>')
        lx += 14 + measure("sans", f"{k} {pct}", 13) + 24
        legend += k + pct
    H = ly + lh
    used = {"display": "".join(m[2] for m in metrics) + "Languages",
            "sans": "".join(m[1] for m in metrics) + "By bytes of code across my public projectsUpdated " + today + legend}
    body = f"<defs>{style(used)}</defs>\n" + "".join(parts)
    return svg(W, H, f"{fmt(d['total_stars'])} stars, {fmt(d['contrib'])} contributions this year, "
                     f"{d['followers']} followers, {d['repos']} public projects", body)


def main() -> None:
    d = collect()
    for name, branch, path, fy, desc, chips in FEATURED:
        raw = fetch(f"https://raw.githubusercontent.com/{USER}/{name}/{branch}/{path}")
        img = cover(raw, 666, 375, fy)
        for t in THEMES:
            write(f"card-{name}-{t}.svg", card(t, name, img, desc, chips, d["stars"].get(name, 0)), DIST)
    for name, desc, meta in MORE:
        for t in THEMES:
            write(f"mini-{name}-{t}.svg", mini(t, DISPLAY_NAME.get(name, name), desc, meta, d["stars"].get(name, 0)), DIST)
    for t in THEMES:
        write(f"stats-{t}.svg", stats(t, d), DIST)
    print(json.dumps({k: d[k] for k in ("total_stars", "followers", "repos", "contrib")}))


if __name__ == "__main__":
    main()
