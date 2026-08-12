# -*- coding: utf-8 -*-
"""
Scraper Thiago Veículos -> feed CSV do catálogo Meta Ads.  (v2)

Mudanças em relação à v1 — todas motivadas por bugs medidos contra o site:

  1. PREÇO vem SEMPRE da meta tag product:price:amount. A v1 varria a página
     inteira atrás de "de R$ X por R$ Y" e acabava pegando o preço do carrossel
     "Sugestões para você": 16 veículos saíram com R$ 114.990 e 5 com
     "de 119.990 por 115.990" que não eram deles.
  2. Tudo que é lido do texto agora sai só da REGIÃO PRINCIPAL (o HTML antes de
     "Sugestões para você"). Nada de contaminar km, carroceria e preço com
     dados de outro veículo.
  3. Paginação usa registros_por_pagina=18. O site IGNORA qualquer outro valor
     e redireciona pra uma página remapeada — era isso que fazia pular veículo.
  4. "N veículos encontrados" é lido do TEXTO (o número vem dentro de <strong>,
     por isso a v1 nunca conseguia ler e nunca conferia o total).
  5. Câmbio, combustível e portas saem da <title> e da ficha técnica — a v1
     adivinhava pela versão e deixava 47% dos câmbios em branco.
  6. Travas: se faltar veículo, se o total não bater ou se o estoque encolher
     mais de 20% de um dia pro outro, o robô FALHA sem sobrescrever o feed bom.
  7. Grava docs/divergencias.json com o que está errado na origem
     (ex.: picape cadastrada como "Conversível/Cupê" no site).

Python 3.10+. Sem navegador: requests + beautifulsoup4 + lxml.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import time
import html as html_lib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

import config as cfg

# ---------------------------------------------------------------------------
# Infra de rede
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
TIMEOUT = 25
MAX_WORKERS = 6


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(session: requests.Session, url: str, tries: int = 4) -> str | None:
    """Baixa uma URL e devolve o HTML. Insiste antes de desistir."""
    for tentativa in range(1, tries + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code in (404, 410):
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * tentativa)
    return None


def text_of(fragment_html: str) -> str:
    return BeautifulSoup(fragment_html, "lxml").get_text(" ", strip=True)


# ---------------------------------------------------------------------------
# Etapa 1 — enumerar TODAS as URLs de veículo do estoque
# ---------------------------------------------------------------------------
def _vehicle_link_regex() -> re.Pattern:
    types = "|".join(cfg.VEHICLE_PATH_TYPES)
    base = re.escape(cfg.SITE_BASE)
    return re.compile(
        rf'{base}/({types})/([^/"\'\s]+)/([^/"\'\s]+)/(\d{{4}})/(\d+)'
    )


LINK_RE = _vehicle_link_regex()
TOTAL_RE = re.compile(r"([\d.]+)\s*ve[íi]culos?\s+encontrados", re.IGNORECASE)
PAGE_LINK_RE = re.compile(r"[?&]pagina=(\d+)")


def _links_da_pagina(page_html: str) -> dict[str, dict]:
    achados: dict[str, dict] = {}
    for match in LINK_RE.finditer(page_html):
        vtype, make_slug, _slug, year, vid = match.groups()
        achados.setdefault(vid, {
            "url": match.group(0),
            "vehicle_id": vid,
            "vehicle_type": vtype,
            "make_slug": make_slug,
            "year_url": year,
        })
    return achados


def url_estoque(pagina: int) -> str:
    # ATENÇÃO: o site só aceita registros_por_pagina=18. Outro valor gera um
    # redirect que embaralha o número da página e faz o robô pular veículos.
    return (f"{cfg.SITE_BASE}{cfg.ESTOQUE_PATH}"
            f"?pagina={pagina}&registros_por_pagina={cfg.PAGE_SIZE}")


def get_inventory(session: requests.Session):
    """Percorre o estoque inteiro. Devolve (lista, total_do_site, paginas_falhas)."""
    encontrados: dict[str, dict] = {}
    total_site = None
    falhas: list[int] = []

    primeira = fetch(session, url_estoque(1))
    if not primeira:
        return [], None, [1]

    m = TOTAL_RE.search(text_of(primeira))
    if m:
        total_site = int(m.group(1).replace(".", ""))

    paginas_linkadas = [int(p) for p in PAGE_LINK_RE.findall(primeira)]
    ultima = max(paginas_linkadas) if paginas_linkadas else 0
    if total_site:
        ultima = max(ultima, math.ceil(total_site / cfg.PAGE_SIZE))
    ultima = min(ultima or cfg.MAX_PAGES, cfg.MAX_PAGES)

    encontrados.update(_links_da_pagina(primeira))
    print(f"  pagina 1: {len(encontrados)} "
          f"(site informa {total_site}, {ultima} paginas)")

    for pagina in range(2, ultima + 1):
        html = fetch(session, url_estoque(pagina))
        if not html:
            print(f"  pagina {pagina}: FALHOU")
            falhas.append(pagina)
            continue
        antes = len(encontrados)
        encontrados.update(_links_da_pagina(html))
        print(f"  pagina {pagina}: +{len(encontrados) - antes} "
              f"(acumulado {len(encontrados)})")

    # Se ainda faltou, varre algumas páginas extras (estoque pode ter crescido)
    if total_site and len(encontrados) < total_site:
        for pagina in range(ultima + 1, min(ultima + 4, cfg.MAX_PAGES) + 1):
            html = fetch(session, url_estoque(pagina))
            if not html:
                break
            antes = len(encontrados)
            encontrados.update(_links_da_pagina(html))
            if len(encontrados) == antes:
                break

    return list(encontrados.values()), total_site, falhas


# ---------------------------------------------------------------------------
# Etapa 2 — extrair os dados de UMA página de veículo
# ---------------------------------------------------------------------------
META_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)\s*=\s*"([^"]+)"[^>]*?content\s*=\s*"([^"]*)"',
    re.IGNORECASE,
)
META_RE_ALT = re.compile(
    r'<meta\s+[^>]*?content\s*=\s*"([^"]*)"[^>]*?(?:property|name)\s*=\s*"([^"]+)"',
    re.IGNORECASE,
)
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# "... 8V 4p Flex 4 portas, câmbio Manual em Rio Verde - Thiago Veículos"
TITLE_SPEC_RE = re.compile(
    r"([A-Za-zÀ-ÿ]+)\s+(\d+)\s*portas?\s*,\s*c[âa]mbio\s+([A-Za-zÀ-ÿ]+)",
    re.IGNORECASE,
)

SUGESTOES_RE = re.compile(r"sugest[õo]es", re.IGNORECASE)


def extract_meta(page_html: str) -> dict:
    meta: dict[str, str] = {}
    for key, val in META_RE.findall(page_html):
        meta.setdefault(key.strip().lower(), html_lib.unescape(val).strip())
    for val, key in META_RE_ALT.findall(page_html):
        meta.setdefault(key.strip().lower(), html_lib.unescape(val).strip())
    return meta


def regiao_principal(page_html: str) -> str:
    """HTML só do veículo em questão, sem o carrossel de sugestões."""
    m = SUGESTOES_RE.search(page_html)
    return page_html[: m.start()] if m else page_html


def fatia(texto: str, inicio: str, fim: str) -> str:
    i = texto.lower().find(inicio.lower())
    if i < 0:
        return ""
    j = texto.lower().find(fim.lower(), i)
    return texto[i + len(inicio): j if j > 0 else len(texto)]


def parse_keywords(meta: dict) -> dict:
    """meta keywords = "Marca, Versão completa, Ano, Cor + texto padrão, ..."."""
    partes = [p.strip() for p in meta.get("keywords", "").split(",") if p.strip()]
    out = {"make": "", "version": "", "year": "", "color": ""}
    if len(partes) >= 1:
        out["make"] = partes[0]
    if len(partes) >= 2:
        out["version"] = partes[1]
    if len(partes) >= 3 and re.fullmatch(r"\d{4}", partes[2]):
        out["year"] = partes[2]
    if len(partes) >= 4:
        chunk = partes[3].lower()
        for cor in cfg.KNOWN_COLORS:
            if chunk.startswith(cor):
                out["color"] = partes[3][: len(cor)].strip().title()
                break
        if not out["color"]:
            out["color"] = partes[3].split(" ")[0].strip().title()
    return out


# ATENÇÃO: NÃO amarre esta regex ao host resized-images. A galeria completa vem
# num JSON embutido na página, com as URLs originais no S3
# (autoconf-production.s3.amazonaws.com) e as barras ESCAPADAS (\/). Era isso que
# fazia a v1 achar só 5 fotos de 12 — ela exigia o host e a barra literal.
# Aqui a gente normaliza o escape e casa só pelo CAMINHO, seja qual for o host.
FOTO_RE_TMPL = r"/veiculos/fotos/{vid}/([a-f0-9][a-f0-9\-]{{19,}})\.(?:jpe?g|png|webp)"


def desescapar(texto: str) -> str:
    r"""JSON dentro do HTML vem com \/ e às vezes \u002F no lugar de /."""
    return (texto.replace("\\/", "/")
                 .replace("\\u002F", "/")
                 .replace("\\u002f", "/"))


def extract_images(page_html: str, meta: dict, vehicle_id: str) -> list[str]:
    """Todas as fotos DESTE veículo (filtra pelo id, então pode varrer a página
    inteira sem risco de pegar foto das sugestões)."""
    rx = re.compile(FOTO_RE_TMPL.format(vid=re.escape(vehicle_id)), re.IGNORECASE)
    urls, vistos = [], set()

    ordem = []
    mo = rx.search(desescapar(meta.get("og:image", "")))   # capa vem primeiro
    if mo:
        ordem.append(mo.group(1))
    ordem += rx.findall(desescapar(page_html))

    for uuid in ordem:
        u = uuid.lower()
        if u in vistos:
            continue
        vistos.add(u)
        urls.append(
            f"https://resized-images.autoconf.com.br/{cfg.IMAGE_SIZE}"
            f"/filters:format(jpg)/veiculos/fotos/{vehicle_id}/{uuid}.jpg"
        )
        if len(urls) >= cfg.MAX_IMAGES:
            break
    return urls


def normalize_make(make: str, make_slug: str) -> str:
    m = (make or "").strip()
    if m.lower() in cfg.MAKE_NORMALIZE:
        return cfg.MAKE_NORMALIZE[m.lower()]
    if m:
        return m
    return cfg.MAKE_SLUG_MAP.get(make_slug, make_slug.replace("-", " ").title())


def split_model_version(version_full: str):
    version_full = (version_full or "").strip()
    if not version_full:
        return "", ""
    tokens = version_full.split()
    return tokens[0], " ".join(tokens[1:]).strip()


def mapear(texto: str, mapping: dict) -> str:
    """Casa termos do mapa dentro de `texto`, mais longos primeiro e com limite
    de palavra (evita 'cupe' casar dentro de 'recuperar')."""
    low = f" {(texto or '').lower()} "
    for termo in sorted(mapping, key=len, reverse=True):
        if re.search(rf"(?<![0-9a-zà-ÿ]){re.escape(termo.lower())}(?![0-9a-zà-ÿ])", low):
            return mapping[termo]
    return ""


def _to_int(num_str: str) -> int:
    return int(re.sub(r"[^\d]", "", num_str or "") or 0)


# Sem \s dentro da classe: era isso que grudava números de blocos diferentes
# e produzia km tipo 3.388.099.
KM_INFO_RE = re.compile(r"\bkm\s*[:\-]\s*([\d.]{2,})\s*km", re.IGNORECASE)
KM_FICHA_RE = re.compile(r"([\d.]{3,})\s*km\b", re.IGNORECASE)
ANO_RE = re.compile(r"\b(\d{4})\s*/\s*(\d{4})\b")
PORTAS_RE = re.compile(r"\b(\d)\s*portas?\b", re.IGNORECASE)
DE_POR_RE = re.compile(r"de\s*r\$\s*([\d.]+).{0,60}?por\s*r\$\s*([\d.]+)",
                       re.IGNORECASE | re.DOTALL)

FUEL_TITULO = {
    "flex": "FLEX", "gasolina": "GASOLINE", "diesel": "DIESEL",
    "álcool": "OTHER", "alcool": "OTHER", "etanol": "OTHER",
    "elétrico": "ELECTRIC", "eletrico": "ELECTRIC",
    "híbrido": "HYBRID", "hibrido": "HYBRID",
}

# Modelos conhecidos — servem pra corrigir cadastro errado na origem.
MODELOS_PICKUP = (
    "s10", "hilux", "ranger", "strada", "saveiro", "toro", "montana", "oroch",
    "l200", "triton", "frontier", "amarok", "f-250", "f250", "f-350", "f350",
    "maverick", "rampage", "courier", "d-20", "d20", "hoggar", "pick-up",
    "picape", "p-up",
)
MODELOS_SUV = (
    "compass", "renegade", "creta", "kicks", "tracker", "t-cross", "taos",
    "nivus", "duster", "captur", "tiguan", "hr-v", "hrv", "wr-v", "wrv",
    "pulse", "fastback", "territory", "sw4", "trailblazer", "pajero",
    "outlander", "asx", "cherokee", "commander", "cross", "discovery",
    "range rover", "cayenne", "tucson", "santa fe", "ecosport", "aircross",
    "cactus", "kona", "seltos", "sportage", "corolla cross",
)
MODELOS_MOTO = (
    "cg ", "biz", "titan", "fan ", "bros", "xre", "fazer", "factor", "fz25",
    "pop ", "crosser", "lander", "twister", "cb ", "ybr",
)


def parse_vehicle(session: requests.Session, listing: dict) -> dict | None:
    page_html = fetch(session, listing["url"])
    if not page_html:
        return None

    main_html = regiao_principal(page_html)
    meta = extract_meta(page_html)          # meta tags ficam no <head>, seguras
    kw = parse_keywords(meta)
    main_text = text_of(main_html)

    titulo_tag = ""
    mt = TITLE_TAG_RE.search(page_html)
    if mt:
        titulo_tag = html_lib.unescape(re.sub(r"\s+", " ", mt.group(1))).strip()

    ficha = fatia(main_text, "Ficha técnica", "Opcionais") or main_text
    info = fatia(main_text, "+ Informações", "Enviar mensagem")

    # --- marca / modelo / versão / ano / cor -------------------------------
    make = normalize_make(kw["make"] or meta.get("product:brand", ""),
                          listing["make_slug"])
    version_full = kw["version"]
    model, trim = split_model_version(version_full)
    year = kw["year"] or listing["year_url"]
    mano = ANO_RE.search(ficha)
    if mano:
        year = mano.group(2)          # ano-modelo
    color = kw["color"] or mapear(ficha, {c: c.title() for c in cfg.KNOWN_COLORS})

    # --- PREÇO: meta tag é a única fonte confiável -------------------------
    try:
        price = float(meta.get("product:price:amount", "0") or 0)
    except ValueError:
        price = 0.0
    sale_price = None
    mdp = DE_POR_RE.search(main_html)      # só na região do próprio veículo
    if mdp:
        de = float(_to_int(mdp.group(1)))
        por = float(_to_int(mdp.group(2)))
        # só aceita a promoção se o "por" bater com a meta tag deste veículo
        if de and por and de > por and (not price or abs(por - price) < 1):
            price, sale_price = de, por

    # --- quilometragem ------------------------------------------------------
    km = 0
    mkm = KM_INFO_RE.search(info) or KM_INFO_RE.search(main_text)
    if mkm:
        km = _to_int(mkm.group(1))
    if not km:
        mkm = KM_FICHA_RE.search(ficha)
        if mkm:
            km = _to_int(mkm.group(1))

    # --- câmbio / combustível / portas (da <title>, que é estruturada) -----
    transmission = fuel = portas = ""
    mts = TITLE_SPEC_RE.search(titulo_tag)
    if mts:
        fuel = FUEL_TITULO.get(mts.group(1).lower(), "")
        portas = mts.group(2)
        transmission = mapear(mts.group(3), cfg.TRANSMISSION_MAP)
    if not transmission:
        transmission = (mapear(ficha, cfg.TRANSMISSION_MAP)
                        or mapear(version_full, cfg.TRANSMISSION_MAP))
    if not fuel:
        fuel = mapear(ficha, cfg.FUEL_MAP) or mapear(version_full, cfg.FUEL_MAP)
    if not portas:
        mp = PORTAS_RE.search(ficha)
        portas = mp.group(1) if mp else ""

    # --- carroceria ---------------------------------------------------------
    body_site = mapear(ficha, cfg.BODY_STYLE_MAP)
    alvo = f"{model} {trim} {version_full}".lower()
    body_inferido = ""
    if listing["vehicle_type"] == "motos" or any(k in alvo for k in MODELOS_MOTO):
        body_inferido = "OTHER"
    elif any(k in alvo for k in MODELOS_PICKUP):
        body_inferido = "PICKUP"
    elif any(k in alvo for k in MODELOS_SUV):
        body_inferido = "SUV"

    body_style = body_site
    divergencia = None
    if body_inferido and body_site and body_inferido != body_site:
        divergencia = {"campo": "body_style", "site": body_site,
                       "usado": body_inferido}
        body_style = body_inferido
    if not body_style:
        body_style = body_inferido or (
            "TRUCK" if listing["vehicle_type"] in ("caminhoes", "caminhonetes")
            else "OTHER")

    # --- imagens ------------------------------------------------------------
    images = extract_images(page_html, meta, listing["vehicle_id"])

    # --- disponibilidade / condição ----------------------------------------
    availability = "in stock"
    if "out of stock" in meta.get("product:availability", "").lower():
        availability = "out of stock"
    condition = (meta.get("product:condition", "") or "used").lower()
    if condition not in ("new", "used", "refurbished"):
        condition = "used"
    state = "NEW" if (km <= 100 and condition == "new") else cfg.DEFAULT_STATE

    return {
        "vehicle_id": listing["vehicle_id"],
        "vehicle_type": listing["vehicle_type"],
        "url": meta.get("og:url", listing["url"]),
        "make": make, "model": model, "trim": trim,
        "version_full": version_full,
        "year": year, "color": color,
        "price": price, "sale_price": sale_price,
        "km": km, "portas": portas,
        "transmission": transmission, "fuel": fuel,
        "body_style": body_style,
        "images": images,
        "availability": availability,
        "condition": condition,
        "state_of_vehicle": state,
        "_divergencia": divergencia,
    }


# ---------------------------------------------------------------------------
# Etapa 3 — montar a linha da Meta e gravar
# ---------------------------------------------------------------------------
META_COLUMNS = [
    "id", "vehicle_id", "title", "description", "availability", "condition",
    "price", "sale_price", "url",
    "make", "model", "trim", "year", "body_style", "state_of_vehicle",
    "mileage.unit", "mileage.value",
    "exterior_color", "transmission", "fuel_type",
    "address.addr1", "address.city", "address.region", "address.postal_code",
    "address.country", "neighborhood[0]", "latitude", "longitude",
    "dealer_id", "dealer_name", "stock_number",
    "image[0].url", "image[0].tag[0]",
    "image[1].url", "image[2].url", "image[3].url", "image[4].url",
    "image[5].url", "image[6].url", "image[7].url", "image[8].url",
    "image[9].url", "image[10].url", "image[11].url", "image[12].url",
    "image[13].url", "image[14].url", "image[15].url", "image[16].url",
    "image[17].url", "image[18].url", "image[19].url",
    "custom_label_0", "custom_label_1", "custom_label_2",
    "custom_label_3", "custom_label_4",
]


def price_band(value: float) -> str:
    if value <= 0:
        return "Sem preço"
    if value < 50_000:
        return "Até 50 mil"
    if value < 80_000:
        return "50 a 80 mil"
    if value < 120_000:
        return "80 a 120 mil"
    if value < 200_000:
        return "120 a 200 mil"
    return "Acima de 200 mil"


def money(value) -> str:
    if not value:
        return ""
    return f"{float(value):.2f} {cfg.CURRENCY}"


def build_row(v: dict) -> dict:
    title = re.sub(r"\s+", " ", f"{v['make']} {v['version_full']}").strip()[:150]
    description = cfg.DESCRIPTION_TEMPLATE.format(
        make=v["make"], model=v["model"], version=v["trim"], year=v["year"],
        km=f"{v['km']:,}".replace(",", "."), color=v["color"] or "—",
    ).strip()

    row = {c: "" for c in META_COLUMNS}
    row.update({
        "id": v["vehicle_id"],
        "vehicle_id": v["vehicle_id"],
        "title": title,
        "description": description,
        "availability": v["availability"],
        "condition": v["condition"],
        "price": money(v["price"]),
        "sale_price": money(v["sale_price"]),
        "url": v["url"],
        "make": v["make"], "model": v["model"], "trim": v["trim"],
        "year": v["year"],
        "body_style": v["body_style"],
        "state_of_vehicle": v["state_of_vehicle"],
        "mileage.unit": cfg.MILEAGE_UNIT,
        "mileage.value": v["km"],
        "exterior_color": v["color"],
        "transmission": v["transmission"],
        "fuel_type": v["fuel"],
        "address.addr1": cfg.ADDRESS_ADDR1,
        "address.city": cfg.ADDRESS_CITY,
        "address.region": cfg.ADDRESS_REGION,
        "address.postal_code": cfg.ADDRESS_POSTAL,
        "address.country": cfg.ADDRESS_COUNTRY,
        "neighborhood[0]": cfg.NEIGHBORHOOD,
        "latitude": cfg.LATITUDE,
        "longitude": cfg.LONGITUDE,
        "dealer_id": cfg.DEALER_ID,
        "dealer_name": cfg.DEALER_NAME,
        "stock_number": v["vehicle_id"],
        "custom_label_0": price_band(v["price"]),
        "custom_label_1": v["body_style"],
        "custom_label_2": v["make"],
        "custom_label_3": v["year"],
        "custom_label_4": v["fuel"],
    })
    for i, img in enumerate(v["images"][: cfg.MAX_IMAGES]):
        row[f"image[{i}].url"] = img
    if v["images"]:
        row["image[0].tag[0]"] = title
    return row


def write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=META_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def ler_csv_anterior(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return [r for r in csv.DictReader(f) if r.get("vehicle_id")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Carência: veículo que sumiu do site fica alguns dias como "out of stock"
# ---------------------------------------------------------------------------
def aplicar_carencia(rows: list[dict], anteriores: list[dict]) -> list[dict]:
    dias = getattr(cfg, "DIAS_FORA_DE_ESTOQUE", 0)
    if dias <= 0 or not anteriores:
        return rows

    hist_path = os.path.join(cfg.OUTPUT_DIR, "historico.json")
    hist = {}
    if os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = {}

    hoje = datetime.now(timezone.utc).date()
    atuais = {r["vehicle_id"] for r in rows}
    for vid in atuais:
        hist.pop(vid, None)

    saida = list(rows)
    for r in anteriores:
        vid = r["vehicle_id"]
        if vid in atuais:
            continue
        sumiu_em = hist.setdefault(vid, hoje.isoformat())
        if hoje - datetime.fromisoformat(sumiu_em).date() <= timedelta(days=dias):
            fora = dict(r)
            fora["availability"] = "out of stock"
            saida.append(fora)

    hist = {k: v for k, v in hist.items()
            if hoje - datetime.fromisoformat(v).date() <= timedelta(days=dias)}
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    json.dump(hist, open(hist_path, "w", encoding="utf-8"), indent=2)
    return saida


# ---------------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------------
def write_stats(rows, total_site, listados, falhas_pagina, falhas_veiculo, path):
    com_foto = sum(1 for r in rows if r["image[0].url"])
    stats = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "veiculos_no_site": total_site,
        "veiculos_listados": listados,
        "veiculos_no_feed": len(rows),
        "bate_com_o_site": (total_site is not None and listados == total_site),
        "paginas_que_falharam": falhas_pagina,
        "veiculos_que_falharam": falhas_veiculo,
        "com_foto": com_foto,
        "sem_foto": len(rows) - com_foto,
        "sem_preco": sum(1 for r in rows if not r["price"]),
        "sem_cambio": sum(1 for r in rows if not r["transmission"]),
        "sem_combustivel": sum(1 for r in rows if not r["fuel_type"]),
    }
    json.dump(stats, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return stats


def write_divergencias(veiculos, path):
    itens = []
    for v in veiculos:
        problemas = []
        if v["_divergencia"]:
            d = v["_divergencia"]
            problemas.append(
                f"carroceria no site = {d['site']}, corrigido para {d['usado']}")
        if v["km"] > 400_000:
            problemas.append(f"km fora da curva no cadastro: {v['km']}")
        if not v["price"]:
            problemas.append("sem preço na página")
        if len(v["images"]) < 3:
            problemas.append(f"só {len(v['images'])} foto(s)")
        if not v["color"]:
            problemas.append("sem cor")
        if not v["transmission"]:
            problemas.append("sem câmbio")
        if problemas:
            itens.append({"vehicle_id": v["vehicle_id"],
                          "titulo": f"{v['make']} {v['version_full']}".strip(),
                          "url": v["url"], "problemas": problemas})
    json.dump({"gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "total": len(itens), "itens": itens},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return itens


def write_index(stats: dict, divergencias: int, path: str) -> None:
    ok = (stats["bate_com_o_site"] and not stats["paginas_que_falharam"]
          and not stats["veiculos_que_falharam"])
    cor = "#15803d" if ok else "#b45309"
    selo = ("Feed conferido: bate 1:1 com o site" if ok
            else "Atenção: o feed não fechou 1:1 com o site")
    html = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Feed Meta — {cfg.DEALER_NAME}</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;max-width:680px;margin:48px auto;padding:0 20px;color:#0f172a}}
 a.btn{{display:inline-block;background:#0852C5;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:600}}
 .card{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-top:20px}}
 .selo{{color:{cor};font-weight:700}}
 small{{color:#64748b}}
</style></head><body>
<h1>Feed do catálogo — {cfg.DEALER_NAME}</h1>
<p class="selo">{selo}</p>
<p><a class="btn" href="catalog_vehicles.csv">Baixar catalog_vehicles.csv</a></p>
<div class="card">
 <strong>Última atualização:</strong> {stats['gerado_em_utc']} (UTC)<br>
 <strong>Veículos no site:</strong> {stats['veiculos_no_site']}<br>
 <strong>Linhas no feed:</strong> {stats['veiculos_no_feed']}<br>
 <strong>Com foto:</strong> {stats['com_foto']} · <strong>Sem foto:</strong> {stats['sem_foto']}<br>
 <strong>Sem câmbio:</strong> {stats['sem_cambio']} · <strong>Sem combustível:</strong> {stats['sem_combustivel']}<br>
 <strong>Cadastros com problema na origem:</strong> {divergencias}
 (<a href="divergencias.json">ver lista</a>)
</div>
<p><small>Gerado por automação no GitHub Actions.</small></p>
</body></html>"""
    open(path, "w", encoding="utf-8").write(html)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    print(">> Lendo estoque...")
    session = make_session()
    listings, total_site, falhas_pagina = get_inventory(session)
    print(f">> {len(listings)} veiculos listados (site informa {total_site}).")

    if not listings:
        print("!! Nenhum veiculo encontrado. Abortando sem sobrescrever.",
              file=sys.stderr)
        return 1
    if falhas_pagina:
        print(f"!! Paginas que nao abriram: {falhas_pagina}. "
              f"Abortando sem sobrescrever.", file=sys.stderr)
        return 1
    if total_site and len(listings) != total_site:
        print(f"!! Listei {len(listings)} mas o site diz {total_site}. "
              f"Abortando sem sobrescrever.", file=sys.stderr)
        return 1

    print(">> Baixando os detalhes de cada veiculo...")
    veiculos, falhas_veiculo = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        resultados = list(pool.map(lambda l: parse_vehicle(session, l), listings))
    for listing, v in zip(listings, resultados):
        if v:
            veiculos.append(v)
        else:
            falhas_veiculo.append(listing["vehicle_id"])

    if falhas_veiculo:
        print(f"!! {len(falhas_veiculo)} paginas de veiculo nao abriram: "
              f"{falhas_veiculo[:10]}. Abortando sem sobrescrever.", file=sys.stderr)
        return 1

    veiculos.sort(key=lambda x: x["vehicle_id"])
    rows = [build_row(v) for v in veiculos]

    anteriores = ler_csv_anterior(cfg.OUTPUT_CSV)
    if anteriores and len(rows) < len(anteriores) * 0.8:
        print(f"!! O estoque caiu de {len(anteriores)} para {len(rows)} (>20%). "
              f"Isso costuma ser problema no site, nao venda. "
              f"Abortando sem sobrescrever.", file=sys.stderr)
        return 1

    rows = aplicar_carencia(rows, anteriores)

    write_csv(rows, cfg.OUTPUT_CSV)
    divs = write_divergencias(veiculos,
                              os.path.join(cfg.OUTPUT_DIR, "divergencias.json"))
    stats = write_stats(rows, total_site, len(listings), falhas_pagina,
                        falhas_veiculo, cfg.OUTPUT_STATS)
    write_index(stats, len(divs), cfg.OUTPUT_INDEX)

    print(f">> CSV gravado: {cfg.OUTPUT_CSV}")
    print(f">> {stats['veiculos_no_feed']} linhas | {stats['com_foto']} com foto | "
          f"{stats['sem_cambio']} sem cambio | {stats['sem_combustivel']} sem combustivel")
    print(f">> {len(divs)} veiculo(s) com cadastro problematico no site "
          f"(veja docs/divergencias.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
