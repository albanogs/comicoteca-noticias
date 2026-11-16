#!/usr/bin/env python3
"""Lee el feed RSS de Tomos y Grapas y acumula las noticias en noticias.json.

Solo guarda titular, resumen corto, fecha, enlace, categoría e imagen.
Respeta robots.txt y se identifica con un User-Agent propio.
Uso: python update.py            (normal)
     python update.py --feed f.xml --no-img   (pruebas sin red)
"""
import json, re, sys, time, html, os
import urllib.request, urllib.robotparser
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

FEED = "https://www.tomosygrapas.com/feed/rss/"
SRC = "Tomos y Grapas"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noticias.json")
MAX_ITEMS = 500
UA = "ComicotecaNoticias/1.0 (lector personal de RSS; +https://github.com/albanogs/comicoteca-noticias)"

_rp = None
def allowed(url):
    global _rp
    if _rp is None:
        _rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request("https://www.tomosygrapas.com/robots.txt", headers={"User-Agent": UA})
            _rp.parse(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore").splitlines())
        except Exception as e:
            print("aviso: no se pudo leer robots.txt:", e)
            _rp = False
    return True if _rp is False else _rp.can_fetch(UA, url)

def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout).read()

def clean(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = html.unescape(t)
    t = re.sub(r"\s*(La entrada|The post)\b.*$", "", t, flags=re.S)  # pie que añade WordPress
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(\s*\[?(…|\.\.\.)\]?)+$", "", t).strip()
    return t[:240]

def categoria(cats):
    low = [c.lower() for c in cats]
    if "podcast" in low: return "podcast"
    if any(c in ("videos", "vídeos", "video") for c in low): return "video"
    if any(c.startswith("cine") for c in low): return "cine"
    return "noticias"

def og_image(url):
    try:
        if not allowed(url): return ""
        page = get(url).decode("utf-8", "ignore")[:200000]
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page, re.I)
        u = html.unescape(m.group(1)) if m else ""
        return u if u.startswith("https://") else ""
    except Exception as e:
        print("aviso: sin imagen para", url, "-", e)
        return ""

def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        title = html.unescape((it.findtext("title") or "").strip())
        if not link or not title: continue
        try:
            d = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
        slug = link.rstrip("/").split("/")[-1]
        cats = [c.text.strip() for c in it.findall("category") if c.text]
        out.append({"id": slug, "tit": title, "d": d, "url": link, "res": clean(it.findtext("description")),
                    "cat": categoria(cats), "src": SRC, "img": ""})
    return out

def main():
    args = sys.argv[1:]
    no_img = "--no-img" in args
    if "--feed" in args:
        xml = open(args[args.index("--feed") + 1], "rb").read()
    else:
        if not allowed(FEED):
            print("robots.txt no permite leer el feed; no se hace nada."); return 0
        xml = get(FEED)
    nuevos = parse(xml)
    if not nuevos:
        print("El feed no trajo noticias; no se cambia nada."); return 1

    try:
        actual = json.load(open(OUT, encoding="utf-8"))["items"]
    except Exception:
        actual = []
    por_id = {n["id"]: n for n in actual}
    anadidas = 0
    for n in nuevos:
        if n["id"] in por_id:
            v = por_id[n["id"]]
            for k in ("tit", "res", "cat"):   # el título o el resumen pueden corregirse
                v[k] = n[k]
            continue
        if not no_img:
            n["img"] = og_image(n["url"]); time.sleep(1)
        por_id[n["id"]] = n
        anadidas += 1
    items = sorted(por_id.values(), key=lambda x: x["d"], reverse=True)[:MAX_ITEMS]

    if items == actual:
        print("Sin cambios."); return 0
    data = {"upd": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Guardado: {anadidas} nuevas, {len(items)} en total.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
