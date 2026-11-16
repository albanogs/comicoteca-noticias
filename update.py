#!/usr/bin/env python3
"""Lee el feed RSS de Tomos y Grapas y acumula las noticias en noticias.json.

Solo guarda titular, resumen corto, fecha, enlace, categoría e imagen.
Respeta robots.txt y se identifica con un User-Agent propio.
Uso: python update.py            (normal)
     python update.py --feed "Zona Negativa=f.xml" --no-img   (pruebas sin red)
"""
import json, re, sys, time, html, os
import urllib.request, urllib.robotparser, urllib.parse
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

# Para añadir otra fuente basta con una línea más aquí.
# prefix: se antepone al id para que no choque con otras webs ("" para la primera).
# cat: categoría fija (por ejemplo "podcast"); None = se deduce de las etiquetas del feed.
SOURCES = [
    {"name": "Tomos y Grapas", "feed": "https://www.tomosygrapas.com/feed/rss/", "home": "https://www.tomosygrapas.com/", "prefix": "", "cat": None},
    {"name": "Zona Negativa", "feed": "https://www.zonanegativa.com/feed/", "home": "https://www.zonanegativa.com/", "prefix": "zn-", "cat": None},
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noticias.json")
MAX_ITEMS = 500
UA = "ComicotecaNoticias/1.0 (lector personal de RSS; +https://github.com/albanogs/comicoteca-noticias)"

_rps = {}
def allowed(url):
    host = urllib.parse.urlsplit(url)
    base = host.scheme + "://" + host.netloc
    if base not in _rps:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
            rp.parse(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore").splitlines())
            _rps[base] = rp
        except Exception as e:
            print("aviso: no se pudo leer robots.txt de", base, "-", e)
            _rps[base] = False
    rp = _rps[base]
    return True if rp is False else rp.can_fetch(UA, url)

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

def parse(xml_bytes, src):
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
        slug = src["prefix"] + link.rstrip("/").split("/")[-1]
        cats = [c.text.strip() for c in it.findall("category") if c.text]
        out.append({"id": slug, "tit": title, "d": d, "url": link, "res": clean(it.findtext("description")),
                    "cat": src["cat"] or categoria(cats), "src": src["name"], "img": ""})
    return out

def feed_de(src):
    """Descarga el feed; si la dirección falla, lo busca en la portada (link rel=alternate)."""
    if not allowed(src["feed"]):
        raise RuntimeError("robots.txt no permite leer el feed")
    try:
        return get(src["feed"])
    except Exception as e:
        print("aviso: feed directo falló (%s); busco en la portada" % e)
        if not allowed(src["home"]):
            raise
        page = get(src["home"]).decode("utf-8", "ignore")[:200000]
        m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)', page, re.I)
        if not m:
            raise
        url = urllib.parse.urljoin(src["home"], html.unescape(m.group(1)))
        print("feed encontrado en:", url)
        return get(url)

def main():
    args = sys.argv[1:]
    no_img = "--no-img" in args
    pruebas = {}                      # --feed "Nombre=archivo.xml" para probar sin red
    for i, a in enumerate(args):
        if a == "--feed":
            n, f = args[i + 1].split("=", 1); pruebas[n] = f
    try:
        actual = json.load(open(OUT, encoding="utf-8"))["items"]
    except Exception:
        actual = []
    por_id = {n["id"]: n for n in actual}
    anadidas = 0; fallos = 0
    for src in SOURCES:
        if pruebas and src["name"] not in pruebas: continue
        try:
            xml = open(pruebas[src["name"]], "rb").read() if pruebas else feed_de(src)
            nuevos = parse(xml, src)
            if not nuevos: raise RuntimeError("el feed no trajo noticias")
        except Exception as e:
            fallos += 1
            print("FALLO en %s: %s" % (src["name"], e))
            continue
        n_src = 0
        for n in nuevos:
            if n["id"] in por_id:
                v = por_id[n["id"]]
                for k in ("tit", "res", "cat"):   # el título o el resumen pueden corregirse
                    v[k] = n[k]
                continue
            if not no_img:
                n["img"] = og_image(n["url"]); time.sleep(1)
            por_id[n["id"]] = n
            anadidas += 1; n_src += 1
        print("%s: %d en el feed, %d nuevas" % (src["name"], len(nuevos), n_src))
    items = sorted(por_id.values(), key=lambda x: x["d"], reverse=True)[:MAX_ITEMS]
    if items == actual:
        print("Sin cambios.")
    else:
        data = {"upd": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("Guardado: %d nuevas, %d en total." % (anadidas, len(items)))
    return 0 if len(SOURCES) - fallos > 0 or pruebas else 1

if __name__ == "__main__":
    sys.exit(main())
