"""Build the site from assets/projects.js.

Run after changing projects, images or the texts below:

    python build.py

It needs Pillow, imageio-ffmpeg, fonttools and brotli:

    python -m pip install --user pillow imageio-ffmpeg fonttools brotli

What it does:
- Downloads every image named in projects.js and makes fast versions in
  assets/media/: GIFs become small looping MP4 videos with a poster frame,
  photos and previews become WebP. Unchanged files are skipped next time.
- Writes assets/media.js, which points the site at those fast versions.
- Writes a static, fully readable page for every project at /work/<id>/.
- Fills in the SEO <head> (title, description, canonical, social cards,
  structured data) of index.html and about/index.html between their
  "build:" markers, and writes 404.html, sitemap.xml, robots.txt,
  site.webmanifest, the icons and the social share image.
"""

import datetime
import hashlib
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
MEDIA_DIR = ROOT / "assets" / "media"

# ───────────────────────────── Site details ─────────────────────────────

SITE = "https://elianyagouni.com"
NAME = "Elian Yagouni"
JOB = "Photographer & Visual Designer"
EMAIL = "contactelianyagouni@gmail.com"
INSTAGRAM = "https://www.instagram.com/septsixdeux/"
BIO = (
    "Algerian photographer and visual designer based in France. A graduate "
    "of ÉSAD Orléans (Orléans School of Art and Design), currently pursuing "
    "a Master’s degree (DNSEP) in Photography and Media Archaeology. Working "
    "across photography, film, and visual design, his practice explores "
    "personal and collective memory, architecture, and the relationship "
    "between images, places, and time."
)
HOME_TITLE = f"{NAME} | {JOB}"
HOME_DESCRIPTION = (
    f"{NAME}, Algerian photographer and visual designer based in France. "
    "Portfolio of photography, film, art direction and visual identity work."
)
ABOUT_TITLE = f"About {NAME} | {JOB}"
ABOUT_DESCRIPTION = (
    f"About {NAME}, Algerian photographer and visual designer in France. "
    "ÉSAD Orléans graduate, Master’s in Photography and Media Archaeology."
)
KNOWS_ABOUT = [
    "Photography", "Visual design", "Art direction", "Graphic design",
    "Visual identity", "Film", "Media archaeology", "Archival research",
    "Book design", "Creative direction",
]
FONT_URL = "https://cd.tarmacq.com/fonts/Satoshi-Variable.ttf"
INK = (56, 39, 1)  # #382701, the site's text colour

PREVIEW_WIDTH = 1600  # home hover previews
PHOTO_WIDTH = 2000  # still photos on project pages
VIDEO_WIDTH = 1200  # GIFs converted to video (shown at most 1100px wide)
VIDEO_CRF = 28  # video quality: lower = sharper but bigger
# Changing any of these re-makes every fast copy on the next build
SETTINGS = f"{PREVIEW_WIDTH}|{PHOTO_WIDTH}|{VIDEO_WIDTH}|{VIDEO_CRF}"

# ───────────────────────────── Helpers ─────────────────────────────


def esc(text):
    return html.escape(str(text), quote=True)


def title_case(name):
    """'PORT OF ALGIERS' -> 'Port of Algiers' for page titles."""
    small = {"of", "and", "the", "a", "an", "in", "on", "for", "to", "et", "les"}
    words = re.split(r"([A-Za-zÀ-ÿ’']+)", name)
    out, first = [], True
    for w in words:
        if re.fullmatch(r"[A-Za-zÀ-ÿ’']+", w):
            lw = w.lower()
            out.append(lw if (lw in small and not first) else lw[:1].upper() + lw[1:])
            first = False
        else:
            out.append(w)
    return "".join(out)


def clip(text, limit=158):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:- ")
    return cut + "…"


def slugify(text):
    text = urllib.parse.unquote(text).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "image"


def version(path):
    """Short content hash for cache-busting ?v= on CSS/JS."""
    return hashlib.sha1((ROOT / path).read_bytes()).hexdigest()[:8]


def write(path, text):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def quote_url(url):
    return urllib.parse.quote(url, safe=":/?=&%")


def fetch(url):
    req = urllib.request.Request(quote_url(url), headers={"User-Agent": "build.py"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read()


def remote_stamp(url):
    """Size + modified date of a remote file, to skip unchanged ones."""
    req = urllib.request.Request(
        quote_url(url), method="HEAD", headers={"User-Agent": "build.py"}
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return f'{res.headers.get("Content-Length")}|{res.headers.get("Last-Modified")}|{res.headers.get("ETag")}'


# ───────────────────────────── Projects ─────────────────────────────


def load_projects():
    """Read window.PROJECTS from assets/projects.js (a JS literal)."""
    src = (ROOT / "assets" / "projects.js").read_text(encoding="utf-8")
    body = src[src.index("[", src.index("window.PROJECTS")) : src.rindex("]") + 1]
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    body = re.sub(r"^(\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', body, flags=re.M)
    body = re.sub(r",(\s*[}\]])", r"\1", body)
    return json.loads(body)


def paragraphs(description):
    return [p.strip() for p in re.split(r"\n\s*\n", description) if p.strip()]


# ───────────────────────────── Media ─────────────────────────────


def ffmpeg():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def even(n):
    return max(2, int(n) // 2 * 2)


def make_webp(data, out, max_width):
    im = Image.open(BytesIO(data))
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    if im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "WEBP", quality=80, method=6)
    return im.width, im.height


def make_video(data, out_mp4, out_poster):
    """Animated GIF -> silent looping H.264 MP4 + first-frame WebP poster."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    src = CACHE / "tmp.gif"
    src.write_bytes(data)
    im = Image.open(src)
    w = even(min(VIDEO_WIDTH, im.width))
    h = even(round(im.height * w / im.width))
    poster = im.convert("RGB").resize((w, h), Image.LANCZOS)
    poster.save(out_poster, "WEBP", quality=78, method=6)
    im.close()
    subprocess.run(
        [
            ffmpeg(), "-y", "-loglevel", "error", "-i", str(src),
            "-vf", f"scale={w}:{h}:flags=lanczos",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(VIDEO_CRF),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
            str(out_mp4),
        ],
        check=True,
    )
    src.unlink()
    return w, h


def is_animated(data):
    if not data[:6] in (b"GIF87a", b"GIF89a"):
        return False
    im = Image.open(BytesIO(data))
    return getattr(im, "n_frames", 1) > 1


def build_media(projects):
    """Make fast copies of every image; returns {original url: info}."""
    manifest_path = CACHE / "media.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    media, keep = {}, set()

    jobs = []
    for p in projects:
        jobs.append((p["id"], p["previewImage"], "preview"))
        jobs += [(p["id"], url, "photo") for url in p.get("photos", [])]

    for pid, url, kind in jobs:
        if url in media:
            continue
        try:
            stamp = remote_stamp(url)
        except Exception as e:  # unreachable: keep using the original URL
            print(f"  ! skipped {url}: {e}")
            continue
        old = manifest.get(url)
        if old and old["stamp"] == stamp and old["kind"] == kind and old.get("settings") == SETTINGS and all(
            (ROOT / f.lstrip("/")).exists() for f in old["files"]
        ):
            media[url] = old["info"]
            keep.update(old["files"])
            continue

        print(f"  optimizing {urllib.parse.unquote(url)}")
        data = fetch(url)
        base = f"/assets/media/{pid}/{'preview' if kind == 'preview' else slugify(url)}"
        if kind == "photo" and is_animated(data):
            mp4, poster = base + ".mp4", base + ".webp"
            w, h = make_video(data, ROOT / mp4.lstrip("/"), ROOT / poster.lstrip("/"))
            info = {"type": "video", "src": mp4, "poster": poster, "w": w, "h": h}
            files = [mp4, poster]
        else:
            webp = base + ".webp"
            w, h = make_webp(data, ROOT / webp.lstrip("/"), PREVIEW_WIDTH if kind == "preview" else PHOTO_WIDTH)
            info = {"type": "image", "src": webp, "w": w, "h": h}
            files = [webp]
        before, after = len(data), sum((ROOT / f.lstrip("/")).stat().st_size for f in files)
        print(f"    {before / 1e6:.1f} MB -> {after / 1e6:.2f} MB")
        manifest[url] = {"stamp": stamp, "kind": kind, "settings": SETTINGS, "info": info, "files": files}
        media[url] = info
        keep.update(files)

    # Remove fast copies of images no longer used
    if MEDIA_DIR.exists():
        for f in MEDIA_DIR.rglob("*"):
            rel = "/" + f.relative_to(ROOT).as_posix()
            if f.is_file() and rel not in keep:
                f.unlink()
        for d in sorted(MEDIA_DIR.rglob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    manifest = {u: m for u, m in manifest.items() if u in media}
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return media


# ───────────────────────────── Assets ─────────────────────────────


def build_font():
    out = ROOT / "assets" / "fonts" / "satoshi-variable.woff2"
    ttf = CACHE / "satoshi-variable.ttf"
    if not ttf.exists():
        ttf.write_bytes(fetch(FONT_URL))
    if not out.exists():
        from fontTools.ttLib import TTFont

        out.parent.mkdir(parents=True, exist_ok=True)
        font = TTFont(ttf)
        font.flavor = "woff2"
        font.save(out)
    return ttf


def build_icons():
    """Icons from icon-source.png (512px+ square, if present) or favicon.ico."""
    source = ROOT / "icon-source.png"
    im = Image.open(source if source.exists() else ROOT / "favicon.ico")
    if not source.exists() and hasattr(im, "ico"):
        im = im.ico.getimage(max(im.ico.sizes()))
    im = im.convert("RGBA")
    for name, size in [
        ("favicon-96x96.png", 96),
        ("apple-touch-icon.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
    ]:
        icon = im.resize((size, size), Image.LANCZOS)
        if name == "apple-touch-icon.png":  # iOS shows transparency as black
            bg = Image.new("RGBA", icon.size, "white")
            icon = Image.alpha_composite(bg, icon).convert("RGB")
        icon.save(ROOT / name, optimize=True)


def build_og_image(ttf):
    """1200x630 share image: the name in full bold, like the site."""
    w, h = 1200, 630
    im = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(im)

    def font(size, weight):
        f = ImageFont.truetype(str(ttf), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        return f

    big = font(150, 900)
    while draw.textlength(NAME.upper(), font=big) > w - 160:
        big = font(big.size - 4, 900)
    small = font(40, 400)
    draw.text((80, h - 80 - 52 - 24), NAME.upper(), font=big, fill=INK, anchor="ls")
    draw.text((84, h - 80), JOB, font=small, fill=INK, anchor="ls")
    im.save(ROOT / "og-image.jpg", quality=88, optimize=True, progressive=True)
    return w, h


# ───────────────────────────── HTML ─────────────────────────────


def person_ld():
    return {
        "@type": "Person",
        "@id": f"{SITE}/#person",
        "name": NAME,
        "alternateName": "EY",
        "url": f"{SITE}/",
        "image": f"{SITE}/og-image.jpg",
        "jobTitle": ["Photographer", "Visual Designer"],
        "description": BIO,
        "email": f"mailto:{EMAIL}",
        "nationality": {"@type": "Country", "name": "Algeria"},
        "homeLocation": {"@type": "Country", "name": "France"},
        "alumniOf": {
            "@type": "CollegeOrUniversity",
            "name": "ÉSAD Orléans (École Supérieure d’Art et de Design d’Orléans)",
            "url": "https://www.esad-orleans.fr/",
        },
        "knowsAbout": KNOWS_ABOUT,
        "sameAs": [INSTAGRAM],
    }


def website_ld():
    return {
        "@type": "WebSite",
        "@id": f"{SITE}/#website",
        "url": f"{SITE}/",
        "name": NAME,
        "alternateName": ["EY", f"{NAME} Portfolio"],
        "description": HOME_DESCRIPTION,
        "inLanguage": "en",
        "publisher": {"@id": f"{SITE}/#person"},
        "author": {"@id": f"{SITE}/#person"},
    }


def head(*, title, description, path, og_type="website", image=None, ld=(), preload=None):
    url = SITE + path
    image = image or {"src": "/og-image.jpg", "w": 1200, "h": 630, "alt": f"{NAME} | {JOB}"}
    graph = json.dumps(
        {"@context": "https://schema.org", "@graph": [person_ld(), website_ld(), *ld]},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    lines = [
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        f"<title>{esc(title)}</title>",
        f'<meta name="description" content="{esc(description)}" />',
        f'<link rel="canonical" href="{url}" />',
        '<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />',
        f'<meta name="author" content="{NAME}" />',
        '<meta name="theme-color" content="#ffffff" />',
        '<meta name="format-detection" content="telephone=no" />',
        f'<link rel="alternate" hreflang="en" href="{url}" />',
        f'<link rel="alternate" hreflang="x-default" href="{url}" />',
        '<link rel="preload" href="/assets/fonts/satoshi-variable.woff2" as="font" type="font/woff2" crossorigin />',
    ]
    if preload:
        lines.append(f'<link rel="preload" href="{preload}" as="image" fetchpriority="high" />')
    lines += [
        f'<link rel="stylesheet" href="/assets/styles.css?v={version("assets/styles.css")}" />',
        '<link rel="icon" href="/favicon.ico" sizes="32x32" />',
        '<link rel="icon" href="/favicon-96x96.png" type="image/png" sizes="96x96" />',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />',
        '<link rel="manifest" href="/site.webmanifest" />',
        f'<meta name="apple-mobile-web-app-title" content="{NAME}" />',
        f'<meta name="application-name" content="{NAME}" />',
        f'<meta property="og:site_name" content="{NAME}" />',
        f'<meta property="og:title" content="{esc(title)}" />',
        f'<meta property="og:description" content="{esc(description)}" />',
        f'<meta property="og:type" content="{og_type}" />',
        f'<meta property="og:url" content="{url}" />',
        f'<meta property="og:image" content="{SITE}{image["src"]}" />',
        f'<meta property="og:image:width" content="{image["w"]}" />',
        f'<meta property="og:image:height" content="{image["h"]}" />',
        f'<meta property="og:image:alt" content="{esc(image["alt"])}" />',
        '<meta property="og:locale" content="en_US" />',
    ]
    if og_type == "profile":
        lines += [
            '<meta property="profile:first_name" content="Elian" />',
            '<meta property="profile:last_name" content="Yagouni" />',
        ]
    lines += [
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{esc(title)}" />',
        f'<meta name="twitter:description" content="{esc(description)}" />',
        f'<meta name="twitter:image" content="{SITE}{image["src"]}" />',
        f'<meta name="twitter:image:alt" content="{esc(image["alt"])}" />',
        f'<script type="application/ld+json">{graph}</script>',
        '<script>window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };</script>',
        '<script defer src="/_vercel/insights/script.js"></script>',
    ]
    return "\n".join("    " + l for l in lines)


def scripts(*names):
    return "\n".join(
        f'    <script src="/assets/{n}?v={version("assets/" + n)}" defer></script>' for n in names
    )


def project_links(projects, media):
    cols = []
    for col in ("left", "right"):
        links = "".join(
            f'<a class="project-link" href="/work/{esc(p["id"])}/" '
            f'data-preview="{esc(media.get(p["previewImage"], {}).get("src", p["previewImage"]))}">{esc(p["name"])}</a>'
            for p in projects
            if (p.get("column") or "right") == col
        )
        cols.append(f'<div class="projects__column">{links}</div>')
    return "".join(cols)


def media_tag(url, media, alt, first):
    m = media.get(url)
    size = f' width="{m["w"]}" height="{m["h"]}"' if m else ""
    if m and m["type"] == "video":
        # Videos below the first start loading only when scrolled near
        src = f'src="{m["src"]}"' if first else f'data-src="{m["src"]}" preload="none"'
        return (
            f'<video {src} poster="{m["poster"]}"{size} autoplay muted loop playsinline '
            f'aria-label="{esc(alt)}" title="{esc(alt)}"></video>'
        )
    load = 'fetchpriority="high"' if first else 'loading="lazy"'
    return f'<img src="{esc(m["src"] if m else url)}" alt="{esc(alt)}"{size} {load} decoding="async" />'


LAZY_VIDEO = (
    "<script>document.querySelectorAll('video[data-src]').forEach(function(v){"
    "if(!('IntersectionObserver'in window)){v.src=v.dataset.src;return}"
    "var o=new IntersectionObserver(function(e){if(e[0].isIntersecting){v.src=v.dataset.src;o.disconnect()}},"
    "{rootMargin:'800px'});o.observe(v)})</script>"
)


def project_body(p, media, next_p=None):
    title = title_case(p["name"])
    gallery = "\n        ".join(
        media_tag(u, media, f"{title} by {NAME}, {i + 1}", i == 0)
        for i, u in enumerate(p.get("photos", []))
    )
    desc = "".join(f"<p>{esc(t)}</p>" for t in paragraphs(p.get("description", "")))
    return f"""    <main class="detail">
      <header class="detail__header">
        <a class="detail__back" href="/">Back</a>
        <div class="detail__heading">
          <h1 class="detail__title">{esc(p["name"])}</h1>
          <p class="detail__subtitle">{esc(p.get("subtitle", ""))}</p>
        </div>
        <span></span>
      </header>

      <div class="detail__description">{desc}</div>

      <section class="detail__gallery" aria-label="{esc(title)} images">
        {gallery}
      </section>

      <p class="watermark"><a class="watermark__text" href="/about/">{NAME.upper()}</a></p>
    </main>
    {LAZY_VIDEO}"""


def project_page(p, media, next_p):
    path = f"/work/{p['id']}/"
    title = title_case(p["name"])
    text = " ".join(paragraphs(p.get("description", "")))
    subtitle = p.get("subtitle", "")
    if "lorem ipsum" in subtitle.lower():
        subtitle = ""
    description = clip(f"{title} by {NAME}" + (f": {subtitle}" if subtitle else "") + f". {text}")

    first = media.get((p.get("photos") or [None])[0]) or media.get(p["previewImage"])
    preview = media.get(p["previewImage"])
    share = preview or first
    image = (
        {"src": share.get("poster", share["src"]), "w": share["w"], "h": share["h"], "alt": f"{title} by {NAME}"}
        if share
        else None
    )
    images = []
    for u in [p["previewImage"], *p.get("photos", [])]:
        m = media.get(u)
        if m:
            images.append(SITE + m.get("poster", m["src"]))
    ld = [
        {
            "@type": "VisualArtwork" if p.get("category") == "personal" else "CreativeWork",
            "@id": f"{SITE}{path}#work",
            "name": title,
            "headline": title,
            "description": text,
            "url": SITE + path,
            "image": images,
            "creator": {"@id": f"{SITE}/#person"},
            "author": {"@id": f"{SITE}/#person"},
            "keywords": subtitle,
            "inLanguage": "en",
            "isPartOf": {"@id": f"{SITE}/#website"},
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": NAME, "item": f"{SITE}/"},
                {"@type": "ListItem", "position": 2, "name": "Work", "item": f"{SITE}/?work"},
                {"@type": "ListItem", "position": 3, "name": title, "item": SITE + path},
            ],
        },
    ]
    preload = first and (first.get("poster") or first["src"])
    return f"""<!doctype html>
<html lang="en">
  <head>
{head(title=f"{title} | {NAME}", description=description, path=path, og_type="article", image=image, ld=ld, preload=preload)}
  </head>
  <body>
{project_body(p, media, next_p)}
  </body>
</html>
"""


def page_404(media):
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Page not found | {NAME}</title>
    <meta name="robots" content="noindex" />
    <link rel="preload" href="/assets/fonts/satoshi-variable.woff2" as="font" type="font/woff2" crossorigin />
    <link rel="stylesheet" href="/assets/styles.css?v={version("assets/styles.css")}" />
    <link rel="icon" href="/favicon.ico" sizes="32x32" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  </head>
  <body>
    <main class="home" id="not-found">
      <nav class="nav">
        <div class="nav__column">
          <a class="nav__item" href="/about/">About</a>
          <a class="nav__item" href="/?work">Work</a>
        </div>
      </nav>
      <section class="about__body">
        <p>This page doesn’t exist. <a href="/">Go to the home page</a>.</p>
      </section>
      <p class="watermark"><a class="watermark__text" href="/about/">{NAME.upper()}</a></p>
    </main>

    <main class="detail" id="project-page" hidden>
      <header class="detail__header">
        <a class="detail__back" href="/">Back</a>
        <div class="detail__heading">
          <h1 class="detail__title"></h1>
          <p class="detail__subtitle"></p>
        </div>
        <span></span>
      </header>
      <div class="detail__description"></div>
      <section class="detail__gallery"></section>
      <p class="watermark"><a class="watermark__text" href="/about/">{NAME.upper()}</a></p>
    </main>

{scripts("projects.js", "media.js", "project.js")}
  </body>
</html>
"""


def redirect_page(target_js, fallback):
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{NAME}</title>
    <meta name="robots" content="noindex, follow" />
    <link rel="canonical" href="{SITE}{fallback}" />
    <meta http-equiv="refresh" content="0; url={fallback}" />
    <script>location.replace({target_js});</script>
  </head>
  <body>
    <a href="{fallback}">{NAME}</a>
  </body>
</html>
"""


def fill(path, blocks):
    """Replace the content between <!-- build:NAME --> markers in a page."""
    text = (ROOT / path).read_text(encoding="utf-8")
    for name, content in blocks.items():
        pattern = re.compile(
            rf"(<!-- build:{name} -->)(.*?)(\s*<!-- /build:{name} -->)", re.S
        )
        if not pattern.search(text):
            raise SystemExit(f"{path}: missing <!-- build:{name} --> markers")
        text = pattern.sub(lambda m: m.group(1) + "\n" + content + m.group(3), text)
    write(path, text)


# ───────────────────────────── Site files ─────────────────────────────


def lastmod(*paths):
    t = max((ROOT / p).stat().st_mtime for p in paths)
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date().isoformat()


def build_sitemap(projects, media):
    def entry(path, mod, image_urls=()):
        imgs = "".join(
            f"\n    <image:image><image:loc>{esc(u)}</image:loc></image:image>" for u in image_urls
        )
        return f"  <url>\n    <loc>{SITE}{path}</loc>\n    <lastmod>{mod}</lastmod>{imgs}\n  </url>"

    data_mod = lastmod("assets/projects.js")
    urls = [
        entry("/", lastmod("index.html", "assets/projects.js"),
              [SITE + "/og-image.jpg"] + [SITE + media[p["previewImage"]]["src"] for p in projects if p["previewImage"] in media]),
        entry("/about/", lastmod("about/index.html"), [SITE + "/og-image.jpg"]),
    ]
    for p in projects:
        imgs = [SITE + m.get("poster", m["src"]) for u in [p["previewImage"], *p.get("photos", [])] if (m := media.get(u))]
        urls.append(entry(f"/work/{p['id']}/", data_mod, imgs))
    write(
        "sitemap.xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(urls)
        + "\n</urlset>\n",
    )


def build_text_files(projects):
    write(
        "robots.txt",
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n",
    )
    write(
        "site.webmanifest",
        json.dumps(
            {
                "name": NAME,
                "short_name": "EY",
                "description": HOME_DESCRIPTION,
                "start_url": "/",
                "scope": "/",
                "display": "standalone",
                "background_color": "#ffffff",
                "theme_color": "#ffffff",
                "icons": [
                    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )
    write("CNAME", "elianyagouni.com\n")
    write(".nojekyll", "")


# ───────────────────────────── Main ─────────────────────────────


def main():
    CACHE.mkdir(exist_ok=True)
    projects = load_projects()
    print(f"{len(projects)} projects")

    print("Media…")
    media = build_media(projects)
    write(
        "assets/media.js",
        "// Generated by build.py: fast copies of the images in projects.js.\n"
        "window.MEDIA = "
        + json.dumps(media, indent=1, ensure_ascii=False)
        + ";\n",
    )

    print("Font, icons, share image…")
    ttf = build_font()
    build_icons()
    build_og_image(ttf)

    print("Pages…")
    for i, p in enumerate(projects):
        nxt = projects[(i + 1) % len(projects)] if len(projects) > 1 else None
        write(f"work/{p['id']}/index.html", project_page(p, media, nxt))
    # Remove pages of deleted projects
    ids = {p["id"] for p in projects}
    for d in (ROOT / "work").iterdir():
        if d.is_dir() and d.name not in ids:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()

    home_ld = [
        {
            "@type": "WebPage",
            "@id": f"{SITE}/#webpage",
            "url": f"{SITE}/",
            "name": HOME_TITLE,
            "description": HOME_DESCRIPTION,
            "isPartOf": {"@id": f"{SITE}/#website"},
            "about": {"@id": f"{SITE}/#person"},
            "mainEntity": {
                "@type": "ItemList",
                "name": "Selected work",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "url": f"{SITE}/work/{p['id']}/", "name": title_case(p["name"])}
                    for i, p in enumerate(projects)
                ],
            },
        }
    ]
    fill(
        "index.html",
        {
            "head": head(title=HOME_TITLE, description=HOME_DESCRIPTION, path="/", ld=home_ld),
            "projects": "          " + project_links(projects, media),
            "scripts": scripts("projects.js", "media.js", "script.js"),
        },
    )
    about_ld = [
        {
            "@type": "ProfilePage",
            "@id": f"{SITE}/about/#webpage",
            "url": f"{SITE}/about/",
            "name": ABOUT_TITLE,
            "description": ABOUT_DESCRIPTION,
            "isPartOf": {"@id": f"{SITE}/#website"},
            "mainEntity": {"@id": f"{SITE}/#person"},
        }
    ]
    fill(
        "about/index.html",
        {"head": head(title=ABOUT_TITLE, description=ABOUT_DESCRIPTION, path="/about/", og_type="profile", ld=about_ld)},
    )
    write("404.html", page_404(media))
    # Old addresses forward to the new clean ones
    write("about.html", redirect_page('"/about/"', "/about/"))
    write(
        "project.html",
        redirect_page(
            'new URLSearchParams(location.search).get("id")'
            ' ? "/work/" + new URLSearchParams(location.search).get("id") + "/" : "/"',
            "/",
        ),
    )

    print("Sitemap, robots, manifest…")
    build_sitemap(projects, media)
    build_text_files(projects)
    print("Done.")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
