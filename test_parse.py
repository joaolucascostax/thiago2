# -*- coding: utf-8 -*-
"""
Teste de fumaça, SEM internet.

O HTML aqui é modelado na estrutura REAL da página do site (Autoconf), inclusive
com o carrossel "Sugestões para você" no fim — que é exatamente de onde a v1
puxava preço e km errados.

Rode com:  python test_parse.py
"""
import scraper as s
import config as cfg

VID = "1029822"
BASE = cfg.SITE_BASE

# Página real simplificada: Gol 2013, R$ 34.990, 171.007 km, câmbio Manual,
# cadastrado no site com carroceria "Conversível/Cupê" (erro do cadastro).
# No fim, sugestões com "de R$ 114.990 por R$ 114.990" e outros km.
HTML = f"""<!doctype html><html><head>
<meta charset="utf-8">
<title>VolksWagen Gol (novo) 1.6 Mi Total Flex 8V 4p Flex 4 portas, c&acirc;mbio Manual em Rio Verde - Thiago Ve&iacute;culos</title>
<meta property="og:url" content="{BASE}/carros/vw-volkswagen/gol-novo-1-6-mi-total-flex-8v-4p/2013/{VID}">
<meta property="og:image" content="https://resized-images.autoconf.com.br/1000x750/filters:format(jpg)/veiculos/fotos/{VID}/509a2520-7791-48e7-ab65-408c9fc99ade.jpg">
<meta property="product:price:amount" content="34990.00">
<meta property="product:price:currency" content="BRL">
<meta property="product:availability" content="in stock">
<meta property="product:condition" content="used">
<meta property="product:brand" content="VolksWagen">
<meta name="keywords" content="VolksWagen, Gol (novo) 1.6 Mi Total Flex 8V 4p, 2013, Branco loja de carro, revenda, Thiago Ve&iacute;culos">
</head><body>
<div class="galeria">
  <img src="https://resized-images.autoconf.com.br/951x720/filters:format(jpg)/veiculos/fotos/{VID}/509a2520-7791-48e7-ab65-408c9fc99ade.jpg">
  <img src="https://resized-images.autoconf.com.br/470x354/filters:format(webp)/veiculos/fotos/{VID}/6973286b-9c65-4889-9d4e-7f43c248363e.jpg">
  <img src="https://resized-images.autoconf.com.br/470x354/filters:format(jpg)/veiculos/fotos/{VID}/562bb804-eb3a-4a23-a740-37698387aaad.jpg">
</div>
<!-- galeria completa: JSON embutido, barras escapadas, host S3 (era o que a v1 perdia) -->
<script>window.__DATA__={{"fotos":[
 "https:\\/\\/autoconf-production.s3.amazonaws.com\\/veiculos\\/fotos\\/{VID}\\/509a2520-7791-48e7-ab65-408c9fc99ade.jpg",
 "https:\\/\\/autoconf-production.s3.amazonaws.com\\/veiculos\\/fotos\\/{VID}\\/11111111-aaaa-bbbb-cccc-000000000001.jpg",
 "https:\\/\\/autoconf-production.s3.amazonaws.com\\/veiculos\\/fotos\\/{VID}\\/11111111-aaaa-bbbb-cccc-000000000002.jpg",
 "https:\\/\\/resized-images.autoconf.com.br\\/470x354\\/filters:format(webp)\\/veiculos\\/fotos\\/{VID}\\/11111111-aaaa-bbbb-cccc-000000000003.jpg"
]}};</script>
<h2>VolksWagen Gol</h2><h3>Gol (novo) 1.6 Mi Total Flex 8V 4p</h3>
<div class="preco"><strong>R$ 34.990</strong></div>
<h4>Ficha t&eacute;cnica</h4>
<ul><li>Manual</li><li>2012/2013</li><li>171.007 km</li><li>Branco</li>
<li>4 portas</li><li>Convers&iacute;vel/Cup&ecirc;</li></ul>
<h4>Opcionais</h4><ul><li>Airbag motorista</li><li>Ar-condicionado</li></ul>
<h4>+ Informa&ccedil;&otilde;es</h4>
<p>A procura de um VolksWagen Gol seminovo? Ano: 2012/2013 KM: 171007 km.</p>
<button>Enviar mensagem</button>
<h2>Sugest&otilde;es para voc&ecirc;</h2>
<div class="card"><a href="{BASE}/carros/fiat/toro-freedom/2022/894060">Fiat Toro</a>
  <span>78.400 km</span><span>de R$ 114.990</span><span>por R$ 114.990</span>
  <img src="https://resized-images.autoconf.com.br/410x308/filters:format(jpg)/veiculos/fotos/894060/ffffffff-0000-1111-2222-333333333333.jpg">
</div>
</body></html>"""


class FakeSession:
    def __init__(self, html):
        self.html = html


def fake_fetch(session, url, tries=3):
    return session.html


def main():
    s.fetch = fake_fetch  # intercepta a rede
    listing = {
        "url": f"{BASE}/carros/vw-volkswagen/gol-novo-1-6-mi-total-flex-8v-4p/2013/{VID}",
        "vehicle_id": VID, "vehicle_type": "carros",
        "make_slug": "vw-volkswagen", "year_url": "2013",
    }
    v = s.parse_vehicle(FakeSession(HTML), listing)

    esperado = {
        "make": "Volkswagen",
        "model": "Gol",
        "year": "2013",
        "color": "Branco",
        "price": 34990.0,          # <- e NAO 114990 vindo das sugestoes
        "sale_price": None,        # <- e NAO "de 114.990 por 114.990"
        "km": 171007,              # <- e NAO 78400 da sugestao
        "transmission": "AUTOMATIC" if False else "MANUAL",
        "fuel": "FLEX",
        "portas": "4",
        "body_style": "OTHER",     # Gol nao e picape/SUV -> fica o do site
        "availability": "in stock",
    }

    falhas = []
    for campo, val in esperado.items():
        if campo == "body_style":
            continue  # conferido abaixo
        if v[campo] != val:
            falhas.append(f"  {campo}: esperado {val!r}, veio {v[campo]!r}")

    # o site cadastrou como Conversivel/Cupe; nao e picape nem SUV, entao
    # o valor do site e mantido (o alerta sai em divergencias.json)
    if v["body_style"] != "CONVERTIBLE":
        falhas.append(f"  body_style: esperado 'CONVERTIBLE', veio {v['body_style']!r}")

    # as fotos tem que ser todas deste veiculo, na resolucao configurada
    # 3 da galeria visivel + 3 novas do JSON escapado/S3 = 6 unicas
    if len(v["images"]) != 6:
        falhas.append(f"  images: esperado 6, veio {len(v['images'])}")
    for u in v["images"]:
        if f"/veiculos/fotos/{VID}/" not in u:
            falhas.append(f"  foto de outro veiculo no feed: {u}")
        if cfg.IMAGE_SIZE not in u:
            falhas.append(f"  foto fora do tamanho {cfg.IMAGE_SIZE}: {u}")

    # a linha final da Meta
    row = s.build_row(v)
    if row["price"] != "34990.00 BRL":
        falhas.append(f"  row price: veio {row['price']!r}")
    if row["id"] != VID:
        falhas.append("  coluna id ausente/errada")

    if falhas:
        print("FALHOU:")
        print("\n".join(falhas))
        return 1
    print("OK — preço, km, câmbio, combustível e fotos saíram corretos, "
          "sem contaminação do carrossel de sugestões.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
