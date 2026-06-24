# -*- coding: utf-8 -*-
"""
Scraper Thiago Veículos -> feed CSV do catálogo Meta Ads.

Como funciona (visão geral):
  1. Lê a página de estoque (paginada) e junta a lista de URLs de cada veículo.
  2. Abre cada veículo e extrai os dados de forma robusta, SEM depender do
     layout do HTML, usando:
        - meta tags no padrão Facebook (product:price, availability, etc.)
        - meta-keywords (marca, versão, ano, cor)
        - o padrão fixo das URLs de foto (/veiculos/fotos/{id}/{uuid}.jpg)
  3. Traduz tudo para as colunas que a Meta espera e grava o CSV.

Roda em qualquer lugar com Python 3.10+. Sem navegador, só `requests`.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import html as html_lib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import config as cfg

# ---------------------------------------------------------------------------
# Infra de rede: sessão com cabeçalho de navegador e retries simples
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
TIMEOUT = 25
MAX_WORKERS = 8        # quantas páginas de veículo baixar em paralelo


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(session: requests.Session, url: str, tries: int = 3) -> str | None:
    """Baixa uma URL e devolve o HTML. Tenta de novo em caso de erro."""
    for attempt in range(1, tries + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            # 404/410 = página sumiu; não adianta insistir
            if r.status_code in (404, 410):
                return None
        except requests.RequestException:
            pass
        time.sleep(1.2 * attempt)
    return None


# ---------------------------------------------------------------------------
# Etapa 1 — enumerar as URLs de todos os veículos do estoque
# ---------------------------------------------------------------------------
def _vehicle_link_regex() -> re.Pattern:
    types = "|".join(cfg.VEHICLE_PATH_TYPES)
    base = re.escape(cfg.SITE_BASE)
    # Captura: 1=url completa, 2=tipo, 3=marca(slug), 4=slug-versão, 5=ano, 6=id
    return re.compile(
        rf'{base}/({types})/([^/"\'\s]+)/([^/"\'\s]+)/(\d{{4}})/(\d+)'
    )


LINK_RE = _vehicle_link_regex()
TOTAL_RE = re.compile(r"([\d.]+)\s*ve[íi]culos?\s+encontrados", re.IGNORECASE)


def get_inventory(session: requests.Session):
    """Percorre o estoque paginado e devolve uma lista de veículos (sem repetir)."""
    found: dict[str, dict] = {}
    total_expected = None

    for pagina in range(1, cfg.MAX_PAGES + 1):
        url = (
            f"{cfg.SITE_BASE}{cfg.ESTOQUE_PATH}"
            f"?registros_por_pagina={cfg.PAGE_SIZE}&pagina={pagina}"
        )
        page_html = fetch(session, url)
        if not page_html:
            break

        if total_expected is None:
            m = TOTAL_RE.search(page_html)
            if m:
                total_expected = int(m.group(1).replace(".", ""))

        new_in_page = 0
        for match in LINK_RE.finditer(page_html):
            full_url, vtype, make_slug, _slug, year, vid = match.groups()
            if vid in found:
                continue
            found[vid] = {
                "url": full_url,
                "vehicle_id": vid,
                "vehicle_type": vtype,
                "make_slug": make_slug,
                "year_url": year,
            }
            new_in_page += 1

        print(f"  página {pagina}: +{new_in_page} (total {len(found)})")

        # parar quando uma página não traz nada novo, ou quando já pegamos tudo
        if new_in_page == 0:
            break
        if total_expected and len(found) >= total_expected:
            break

    return list(found.values()), total_expected


# ---------------------------------------------------------------------------
# Etapa 2 — extrair os dados de uma página de veículo
# ---------------------------------------------------------------------------
META_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)\s*=\s*"([^"]+)"[^>]*?content\s*=\s*"([^"]*)"',
    re.IGNORECASE,
)
# alguns geradores invertem a ordem (content antes de property)
META_RE_ALT = re.compile(
    r'<meta\s+[^>]*?content\s*=\s*"([^"]*)"[^>]*?(?:property|name)\s*=\s*"([^"]+)"',
    re.IGNORECASE,
)


def extract_meta(page_html: str) -> dict:
    meta: dict[str, str] = {}
    for key, val in META_RE.findall(page_html):
        meta.setdefault(key.strip().lower(), html_lib.unescape(val).strip())
    for val, key in META_RE_ALT.findall(page_html):
        meta.setdefault(key.strip().lower(), html_lib.unescape(val).strip())
    return meta


def parse_keywords(meta: dict) -> dict:
    """
    A meta-keywords da página de veículo começa com:
        marca, versão completa, ano, cor + (texto padrão da loja)
    Ex.: "Renault, OROCH Outsider 1.3Tce Flex Aut., 2025, Prata loja de carro, ..."
    """
    raw = meta.get("keywords", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out = {"make": "", "version": "", "year": "", "color": ""}
    if len(parts) >= 1:
        out["make"] = parts[0]
    if len(parts) >= 2:
        out["version"] = parts[1]
    if len(parts) >= 3 and re.fullmatch(r"\d{4}", parts[2]):
        out["year"] = parts[2]
    if len(parts) >= 4:
        # o 4º item costuma vir "Cor loja de carro" (cor grudada no texto padrão)
        chunk = parts[3].lower()
        for color in cfg.KNOWN_COLORS:
            if chunk.startswith(color):
                out["color"] = parts[3][: len(color)].strip().title()
                break
        if not out["color"]:
            # pega só a 1ª palavra como cor (melhor esforço)
            out["color"] = parts[3].split(" ")[0].strip().title()
    return out


# Casa qualquer URL de foto DESTE veículo, seja qual for o prefixo de
# redimensionamento (ex.: ".../410x308/filters:format(jpg)/veiculos/fotos/{id}/...").
# Não excluímos ")" porque ele aparece em "filters:format(jpg)".
FOTO_RE_TMPL = (
    r"resized-images\.autoconf\.com\.br/[^\"'\s]*?/veiculos/fotos/{vid}/"
    r"([a-f0-9][a-f0-9\-]+)\.(?:jpe?g|png|webp)"
)


def extract_images(page_html: str, vehicle_id: str) -> list[str]:
    """Pega as fotos DESTE veículo (filtra pelo id, ignora fotos de 'sugestões')."""
    rx = re.compile(FOTO_RE_TMPL.format(vid=re.escape(vehicle_id)), re.IGNORECASE)
    urls, seen = [], set()
    for uuid in rx.findall(page_html):
        if uuid in seen:
            continue
        seen.add(uuid)
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
    """'OROCH Outsider 1.3Tce Flex Aut.' -> model='OROCH', trim='Outsider 1.3Tce ...'"""
    version_full = version_full.strip()
    if not version_full:
        return "", ""
    tokens = version_full.split()
    model = tokens[0]
    trim = " ".join(tokens[1:]).strip()
    return model, trim


def infer_from_version(version_full: str, mapping: dict) -> str:
    text = f" {version_full.lower()} "
    for key, value in mapping.items():
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", text):
            return value
    return ""


def extract_body_style(page_text: str) -> str:
    low = page_text.lower()
    # tenta os termos mais longos primeiro (ex.: 'utilitário esportivo' antes de 'van')
    for term in sorted(cfg.BODY_STYLE_MAP, key=len, reverse=True):
        if term in low:
            return cfg.BODY_STYLE_MAP[term]
    return ""


KM_LABEL_RE = re.compile(r"km\s*[:\-]?\s*([\d.\s]+)\s*km", re.IGNORECASE)
KM_ANY_RE = re.compile(r"([\d.]{3,})\s*km", re.IGNORECASE)
DE_POR_RE = re.compile(r"de\s*r\$\s*([\d.]+).{0,40}?por\s*r\$\s*([\d.]+)",
                       re.IGNORECASE | re.DOTALL)


def _to_int(num_str: str) -> int:
    return int(re.sub(r"[^\d]", "", num_str) or 0)


def parse_vehicle(session: requests.Session, listing: dict) -> dict | None:
    page_html = fetch(session, listing["url"])
    if not page_html:
        return None

    meta = extract_meta(page_html)
    kw = parse_keywords(meta)
    soup = BeautifulSoup(page_html, "lxml")
    page_text = soup.get_text(" ", strip=True)

    # --- marca / modelo / versão / ano / cor ---
    make = normalize_make(kw["make"] or meta.get("product:brand", ""),
                          listing["make_slug"])
    version_full = kw["version"]
    model, trim = split_model_version(version_full)
    year = kw["year"] or listing["year_url"]
    color = kw["color"]

    # --- preço (meta tag é a fonte autoritativa) ---
    try:
        current_price = float(meta.get("product:price:amount", "0") or 0)
    except ValueError:
        current_price = 0.0
    price = current_price
    sale_price = None
    m = DE_POR_RE.search(page_html) or DE_POR_RE.search(page_text)
    if m:
        de = float(_to_int(m.group(1)))
        por = float(_to_int(m.group(2)))
        if de and por and de > por:
            price, sale_price = de, por
        elif por:
            price = por
    if not price and current_price:
        price = current_price

    # --- quilometragem (ancorada no rótulo 'KM:' pra não pegar km de sugestões) ---
    km = 0
    mkm = KM_LABEL_RE.search(page_text)
    if mkm:
        km = _to_int(mkm.group(1))
    if not km:
        any_km = KM_ANY_RE.search(page_text)
        if any_km:
            km = _to_int(any_km.group(1))

    # --- câmbio / combustível (inferidos da versão = bem confiável) ---
    transmission = infer_from_version(version_full, cfg.TRANSMISSION_MAP)
    fuel = infer_from_version(version_full, cfg.FUEL_MAP)

    # --- carroceria / body_style ---
    body_style = extract_body_style(page_text)
    if not body_style:
        body_style = infer_from_version(version_full, {
            "pick-up": "PICKUP", "picape": "PICKUP", "suv": "SUV",
            "sedan": "SEDAN", "sedã": "SEDAN", "hatch": "HATCHBACK",
        })
    if not body_style:
        body_style = "TRUCK" if listing["vehicle_type"] in ("caminhoes", "caminhonetes") else "OTHER"

    # --- imagens ---
    images = extract_images(page_html, listing["vehicle_id"])
    if not images:
        og = meta.get("og:image", "")
        if og:
            images = [og]

    # --- disponibilidade / condição ---
    availability = "in stock"
    if "out of stock" in (meta.get("product:availability", "").lower()):
        availability = "out of stock"
    condition = (meta.get("product:condition", "") or "used").lower()
    if condition not in ("new", "used", "refurbished"):
        condition = "used"

    state = cfg.DEFAULT_STATE
    if km == 0 and condition == "new":
        state = "NEW"

    return {
        "vehicle_id": listing["vehicle_id"],
        "vehicle_type": listing["vehicle_type"],
        "url": meta.get("og:url", listing["url"]),
        "make": make,
        "model": model,
        "trim": trim,
        "version_full": version_full,
        "year": year,
        "color": color,
        "price": price,
        "sale_price": sale_price,
        "km": km,
        "transmission": transmission,
        "fuel": fuel,
        "body_style": body_style,
        "images": images,
        "availability": availability,
        "condition": condition,
        "state_of_vehicle": state,
    }


# ---------------------------------------------------------------------------
# Etapa 3 — montar a linha no formato da Meta e gravar o CSV
# ---------------------------------------------------------------------------
# Colunas na ordem exata que a Meta lê (cabeçalho = nome dos campos).
META_COLUMNS = [
    "vehicle_id", "title", "description", "availability", "condition",
    "price", "sale_price", "url",
    "make", "model", "trim", "year", "body_style", "state_of_vehicle",
    "mileage.unit", "mileage.value",
    "exterior_color", "transmission", "fuel_type",
    "address.addr1", "address.city", "address.region", "address.postal_code",
    "address.country", "neighborhood[0]", "latitude", "longitude",
    "dealer_id", "dealer_name", "stock_number",
    # fotos
    "image[0].url", "image[0].tag[0]",
    "image[1].url", "image[2].url", "image[3].url", "image[4].url",
    "image[5].url", "image[6].url", "image[7].url", "image[8].url",
    "image[9].url",
    # rótulos pra segmentar campanhas/conjuntos de produtos na Meta
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
    title = f"{v['make']} {v['version_full']}".strip()
    title = re.sub(r"\s+", " ", title)[:150]

    description = cfg.DESCRIPTION_TEMPLATE.format(
        make=v["make"], model=v["model"], version=v["trim"],
        year=v["year"], km=f"{v['km']:,}".replace(",", "."), color=v["color"] or "—",
    ).strip()

    row = {c: "" for c in META_COLUMNS}
    row.update({
        "vehicle_id": v["vehicle_id"],
        "title": title,
        "description": description,
        "availability": v["availability"],
        "condition": v["condition"],
        "price": money(v["price"]),
        "sale_price": money(v["sale_price"]),
        "url": v["url"],
        "make": v["make"],
        "model": v["model"],
        "trim": v["trim"],
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
        # segmentação
        "custom_label_0": price_band(v["price"]),
        "custom_label_1": v["body_style"],
        "custom_label_2": v["make"],
        "custom_label_3": v["year"],
        "custom_label_4": v["fuel"],
    })

    # fotos
    for i, img in enumerate(v["images"][: cfg.MAX_IMAGES]):
        row[f"image[{i}].url"] = img
    if v["images"]:
        row["image[0].tag[0]"] = title

    return row


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=META_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_stats(rows: list[dict], total_expected, path: str) -> None:
    with_image = sum(1 for r in rows if r["image[0].url"])
    stats = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "veiculos_no_feed": len(rows),
        "veiculos_no_site": total_expected,
        "com_foto": with_image,
        "sem_foto": len(rows) - with_image,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    return stats


def write_index(stats: dict, path: str) -> None:
    html = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Feed Meta — {cfg.DEALER_NAME}</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;max-width:680px;margin:48px auto;padding:0 20px;color:#0f172a}}
 a.btn{{display:inline-block;background:#0852C5;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:600}}
 .card{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-top:20px}}
 code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}
 small{{color:#64748b}}
</style></head><body>
<h1>Feed do catálogo — {cfg.DEALER_NAME}</h1>
<p>Atualizado automaticamente todo dia. Use o link abaixo como fonte de dados
no catálogo da Meta (Gerenciador de Comércio → Fonte de dados → Agendada).</p>
<p><a class="btn" href="catalog_vehicles.csv">📄 Baixar catalog_vehicles.csv</a></p>
<div class="card">
 <strong>Última atualização:</strong> {stats['gerado_em_utc']} (UTC)<br>
 <strong>Veículos no feed:</strong> {stats['veiculos_no_feed']}
 (site informa {stats['veiculos_no_site']})<br>
 <strong>Com foto:</strong> {stats['com_foto']} &nbsp;·&nbsp;
 <strong>Sem foto:</strong> {stats['sem_foto']}
</div>
<p><small>Gerado por automação no GitHub Actions.</small></p>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    print(">> Lendo estoque...")
    session = make_session()
    listings, total_expected = get_inventory(session)
    print(f">> {len(listings)} veículos encontrados no estoque "
          f"(site informa {total_expected}).")

    if not listings:
        print("!! Nenhum veículo encontrado. O site mudou? Abortando sem sobrescrever.",
              file=sys.stderr)
        return 1

    print(">> Baixando os detalhes de cada veículo...")
    vehicles: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(parse_vehicle, session, l): l for l in listings}
        for fut in as_completed(futures):
            v = fut.result()
            if v:
                vehicles.append(v)

    vehicles.sort(key=lambda x: x["vehicle_id"])
    rows = [build_row(v) for v in vehicles]

    write_csv(rows, cfg.OUTPUT_CSV)
    stats = write_stats(rows, total_expected, cfg.OUTPUT_STATS)
    write_index(stats, cfg.OUTPUT_INDEX)

    print(f">> CSV gravado: {cfg.OUTPUT_CSV}")
    print(f">> {stats['veiculos_no_feed']} veículos | "
          f"{stats['com_foto']} com foto | {stats['sem_foto']} sem foto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
