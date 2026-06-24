# -*- coding: utf-8 -*-
"""
Teste de fumaça do parsing, SEM acessar a internet.
Monta um HTML parecido com o do site (a partir dos dados reais do OROCH que
levantamos) e confere se cada função extrai o que deveria.
"""
import scraper as s
import config as cfg

VID = "123456"

# HTML sintético no formato da plataforma Autoconf (meta tags FB + fotos + ficha).
SYNthetic = f"""<!doctype html><html><head>
<meta charset="utf-8">
<meta property="og:title" content="Renault OROCH Outsider 1.3Tce Flex Aut. 2025">
<meta property="og:url" content="{cfg.SITE_BASE}/carros/renault/oroch-outsider-1-3tce-flex-aut/2025/{VID}">
<meta property="og:image" content="https://resized-images.autoconf.com.br/410x308/filters:format(jpg)/veiculos/fotos/{VID}/aaaaaaaa-1111-2222-3333-444444444444.jpg">
<meta property="product:price:amount" content="121990.00">
<meta property="product:price:currency" content="BRL">
<meta property="product:availability" content="in stock">
<meta property="product:condition" content="used">
<meta property="product:brand" content="Renault">
<meta name="keywords" content="Renault, OROCH Outsider 1.3Tce Flex Aut., 2025, Prata loja de carro em rio verde, seminovo, financiamento">
<meta name="description" content="OROCH Outsider 2025 prata na Thiago Veículos">
</head><body>
<div class="ficha">
  <span>Marca: Renault</span>
  <span>Modelo: OROCH</span>
  <span>Ano: 2025/2025</span>
  <span>KM: 12.500 km</span>
  <span>Câmbio: Automático</span>
  <span>Cor: Prata</span>
  <span>Portas: 4</span>
  <span>Carroceria: Picape</span>
  <span>Combustível: Flex</span>
</div>
<div class="preco">de R$ 129.990 por R$ 121.990</div>
<div class="galeria">
  <img src="https://resized-images.autoconf.com.br/410x308/filters:format(jpg)/veiculos/fotos/{VID}/aaaaaaaa-1111-2222-3333-444444444444.jpg">
  <img src="https://resized-images.autoconf.com.br/410x308/filters:format(jpg)/veiculos/fotos/{VID}/bbbbbbbb-1111-2222-3333-444444444444.jpg">
  <img src="https://resized-images.autoconf.com.br/410x308/filters:format(jpg)/veiculos/fotos/{VID}/cccccccc-1111-2222-3333-444444444444.jpg">
</div>
<div class="sugestoes">
  <!-- foto de OUTRO veículo: tem que ser IGNORADA (id diferente) -->
  <img src="https://resized-images.autoconf.com.br/410x308/filters:format(jpg)/veiculos/fotos/999999/dddddddd-1111-2222-3333-444444444444.jpg">
</div>
</body></html>"""

listing = {
    "url": f"{cfg.SITE_BASE}/carros/renault/oroch-outsider-1-3tce-flex-aut/2025/{VID}",
    "vehicle_id": VID,
    "vehicle_type": "carros",
    "make_slug": "renault",
    "year_url": "2025",
}


def check(label, got, expected):
    ok = got == expected
    print(f"[{'OK ' if ok else 'XXX'}] {label}: {got!r}" + ("" if ok else f"  (esperado {expected!r})"))
    return ok


def main():
    allok = True

    meta = s.extract_meta(SYNthetic)
    allok &= check("meta og:title", meta.get("og:title"), "Renault OROCH Outsider 1.3Tce Flex Aut. 2025")
    allok &= check("meta price amount", meta.get("product:price:amount"), "121990.00")
    allok &= check("meta availability", meta.get("product:availability"), "in stock")

    kw = s.parse_keywords(meta)
    allok &= check("kw make", kw["make"], "Renault")
    allok &= check("kw version", kw["version"], "OROCH Outsider 1.3Tce Flex Aut.")
    allok &= check("kw year", kw["year"], "2025")
    allok &= check("kw color", kw["color"], "Prata")

    make = s.normalize_make(kw["make"] or meta.get("product:brand", ""), listing["make_slug"])
    allok &= check("make normalizada", make, "Renault")

    model, trim = s.split_model_version(kw["version"])
    allok &= check("model", model, "OROCH")
    allok &= check("trim", trim, "Outsider 1.3Tce Flex Aut.")

    transmission = s.infer_from_version(kw["version"], cfg.TRANSMISSION_MAP)
    allok &= check("transmission", transmission, "AUTOMATIC")

    fuel = s.infer_from_version(kw["version"], cfg.FUEL_MAP)
    allok &= check("fuel", fuel, "FLEX")

    from bs4 import BeautifulSoup
    page_text = BeautifulSoup(SYNthetic, "lxml").get_text(" ", strip=True)

    body = s.extract_body_style(page_text)
    allok &= check("body_style", body, "PICKUP")

    km = s._to_int(s.KM_LABEL_RE.search(page_text).group(1))
    allok &= check("km", km, 12500)

    imgs = s.extract_images(SYNthetic, VID)
    allok &= check("nº de fotos (deste veículo)", len(imgs), 3)
    allok &= check("1ª foto tem tamanho normalizado",
                   imgs[0].startswith(f"https://resized-images.autoconf.com.br/{cfg.IMAGE_SIZE}/"),
                   True)
    allok &= check("foto de sugestão foi ignorada",
                   any("999999" in u for u in imgs), False)

    # de/por
    m = s.DE_POR_RE.search(SYNthetic)
    de = float(s._to_int(m.group(1)))
    por = float(s._to_int(m.group(2)))
    allok &= check("preço de", de, 129990.0)
    allok &= check("preço por", por, 121990.0)

    # build_row completo
    v = s.parse_vehicle.__wrapped__ if hasattr(s.parse_vehicle, "__wrapped__") else None
    # parse_vehicle precisa de rede; montamos o dict manualmente do jeito que ele montaria:
    vehicle = {
        "vehicle_id": VID, "vehicle_type": "carros",
        "url": listing["url"], "make": make, "model": model, "trim": trim,
        "version_full": kw["version"], "year": "2025", "color": "Prata",
        "price": 129990.0, "sale_price": 121990.0, "km": 12500,
        "transmission": "AUTOMATIC", "fuel": "FLEX", "body_style": "PICKUP",
        "images": imgs, "availability": "in stock", "condition": "used",
        "state_of_vehicle": "USED",
    }
    row = s.build_row(vehicle)
    allok &= check("row title", row["title"], "Renault OROCH Outsider 1.3Tce Flex Aut.")
    allok &= check("row price", row["price"], "129990.00 BRL")
    allok &= check("row sale_price", row["sale_price"], "121990.00 BRL")
    allok &= check("row mileage.value", row["mileage.value"], 12500)
    allok &= check("row image[0].url presente", bool(row["image[0].url"]), True)
    allok &= check("row image[2].url presente", bool(row["image[2].url"]), True)
    allok &= check("row custom_label_0 (faixa preço)", row["custom_label_0"], "120 a 200 mil")
    allok &= check("row custom_label_2 (marca)", row["custom_label_2"], "Renault")

    # todos os obrigatórios preenchidos?
    obrig = ["vehicle_id","title","description","price","image[0].url","image[0].tag[0]",
             "url","body_style","address.addr1","address.city","address.country",
             "latitude","longitude","neighborhood[0]","make","model","year",
             "state_of_vehicle","mileage.unit","mileage.value"]
    faltando = [c for c in obrig if row.get(c) in ("", None)]
    allok &= check("campos obrigatórios sem buraco", faltando, [])

    print("\n" + ("== TUDO OK ==" if allok else "== TEM ERRO, revisar acima =="))
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
