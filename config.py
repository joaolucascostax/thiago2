# -*- coding: utf-8 -*-
"""
Configuração do feed Meta Ads — Thiago Veículos.

Este é o ÚNICO arquivo que você normalmente precisa editar.
Tudo aqui é constante da loja: endereço, coordenadas, textos padrão e
os "de-para" que traduzem os termos do site para o que a Meta espera.
"""

# ---------------------------------------------------------------------------
# 1. SITE DE ORIGEM
# ---------------------------------------------------------------------------
SITE_BASE = "https://thiagoveiculosrv.com.br"
ESTOQUE_PATH = "/estoque"

# Quantos veículos pedir por página no estoque. O site aceita esse parâmetro,
# então pedimos um número alto pra puxar tudo em poucas requisições.
PAGE_SIZE = 60
MAX_PAGES = 50            # trava de segurança (nunca deve chegar perto disso)

# Tipos de URL que contam como veículo (o site usa /carros/, /caminhoes/ etc.)
VEHICLE_PATH_TYPES = (
    "carros", "caminhoes", "caminhonetes", "motos", "onibus", "maquinas",
)

# ---------------------------------------------------------------------------
# 2. DADOS DA LOJA (vão para todos os anúncios)
# ---------------------------------------------------------------------------
DEALER_NAME = "Thiago Veículos"
DEALER_ID = "thiago-veiculos-rv"      # identificador livre, só precisa ser estável

ADDRESS_ADDR1 = "Avenida Paulo Roberto Cunha, Quadra L Lote 15"
ADDRESS_CITY = "Rio Verde"
ADDRESS_REGION = "GO"                 # estado / região
ADDRESS_POSTAL = "75901-648"
ADDRESS_COUNTRY = "BR"

# A Meta usa neighborhood[0] como a "área" onde o veículo é ofertado.
# Para busca, o que o comprador digita é a cidade — então deixamos a cidade aqui.
NEIGHBORHOOD = "Rio Verde"

# >>> AJUSTE IMPORTANTE <<<
# Latitude/Longitude são OBRIGATÓRIAS pra Meta. O valor abaixo é o centro de
# Rio Verde (serve pra começar). Pra deixar exato: abra o Google Maps, ache a
# loja, clique com o botão direito no ponto e copie as duas coordenadas.
LATITUDE = -17.7975
LONGITUDE = -50.9266

# Contato (não são campos obrigatórios da Meta, mas usamos no texto/descrição)
PHONE = "+55 64 3622-6273"
WHATSAPP = "+55 64 99276-8851"

# ---------------------------------------------------------------------------
# 3. PADRÕES DO FEED
# ---------------------------------------------------------------------------
CURRENCY = "BRL"
DEFAULT_STATE = "USED"     # estoque é seminovo/usado; 0 km vira NEW automaticamente
MILEAGE_UNIT = "KM"
IMAGE_SIZE = "1000x750"    # tamanho normalizado das fotos (Meta exige >= 600px)
MAX_IMAGES = 10            # quantas fotos por veículo enviar

# Modelo do texto de descrição (gerado a partir dos campos do veículo).
# Use {make} {model} {version} {year} {km} {color} como variáveis.
DESCRIPTION_TEMPLATE = (
    "{make} {model} {version} — Ano {year}, {km} km, cor {color}. "
    "Seminovo com procedência, revisado e com garantia da loja. "
    "Thiago Veículos, em Rio Verde-GO. Agende sua visita ou chame no WhatsApp "
    "que a gente te atende rapidinho."
)

# Saída
OUTPUT_DIR = "docs"                       # vai pro GitHub Pages
OUTPUT_CSV = "docs/catalog_vehicles.csv"  # ESTE é o link que você dá pra Meta
OUTPUT_STATS = "docs/feed_stats.json"
OUTPUT_INDEX = "docs/index.html"

# ---------------------------------------------------------------------------
# 4. DE-PARA: termos do site -> valores aceitos pela Meta
# ---------------------------------------------------------------------------

# Marca: slug da URL -> nome de exibição (fallback caso a meta tag falhe)
MAKE_SLUG_MAP = {
    "audi": "Audi", "gm-chevrolet": "Chevrolet", "chevrolet": "Chevrolet",
    "citroen": "Citroën", "ford": "Ford", "ford-1": "Ford", "fiat": "Fiat",
    "honda": "Honda", "hyundai": "Hyundai", "jeep": "Jeep",
    "land-rover": "Land Rover", "mitsubishi": "Mitsubishi", "porsche": "Porsche",
    "renault": "Renault", "toyota": "Toyota", "vw-volkswagen": "Volkswagen",
    "volkswagen": "Volkswagen", "nissan": "Nissan", "peugeot": "Peugeot",
    "kia": "Kia", "bmw": "BMW", "mercedes-benz": "Mercedes-Benz",
    "chery": "Chery", "caoa-chery": "Caoa Chery", "byd": "BYD",
    "ram": "RAM", "dodge": "Dodge", "suzuki": "Suzuki", "subaru": "Subaru",
    "volvo": "Volvo", "yamaha": "Yamaha", "iveco": "Iveco",
}

# Normalização final de nomes de marca que vêm "torto" nas meta tags
MAKE_NORMALIZE = {
    "volkswagen": "Volkswagen", "gm - chevrolet": "Chevrolet",
    "gm-chevrolet": "Chevrolet", "gm": "Chevrolet",
}

# Carroceria (site) -> body_style (enum Meta).
# Valores aceitos pela Meta: CONVERTIBLE, COUPE, CROSSOVER, ESTATE, HATCHBACK,
# MINIVAN, OTHER, PICKUP, ROADSTER, SEDAN, SMALL_CAR, SUV, TRUCK, VAN, WAGON ...
BODY_STYLE_MAP = {
    "hatch": "HATCHBACK",
    "hatchback": "HATCHBACK",
    "sedã": "SEDAN", "seda": "SEDAN", "sedan": "SEDAN",
    "suv": "SUV", "utilitário esportivo": "SUV", "utilitario esportivo": "SUV",
    "picape": "PICKUP", "picapes": "PICKUP", "pick-up": "PICKUP", "pickup": "PICKUP",
    "minivan": "MINIVAN",
    "van": "VAN", "van/utilitário": "VAN", "van/utilitario": "VAN",
    "utilitário": "VAN", "utilitario": "VAN",
    "conversível": "CONVERTIBLE", "conversivel": "CONVERTIBLE",
    "cupê": "COUPE", "cupe": "COUPE", "coupé": "COUPE", "coupe": "COUPE",
    "perua": "WAGON", "wagon": "WAGON",
    "street": "OTHER",
    "carroceria de ferro": "TRUCK", "carroceria de madeira": "TRUCK",
    "caminhão": "TRUCK", "caminhao": "TRUCK", "truck": "TRUCK",
}

# Combustível (palavra na versão) -> fuel_type (enum Meta).
# Aceitos: DIESEL, ELECTRIC, FLEX, GASOLINE, HYBRID, PETROL, PLUGIN_HYBRID, OTHER
FUEL_MAP = {
    "flex": "FLEX",
    "diesel": "DIESEL", "dies": "DIESEL", "tdi": "DIESEL",
    "gasolina": "GASOLINE",
    "álcool": "OTHER", "alcool": "OTHER", "etanol": "OTHER",
    "elétrico": "ELECTRIC", "eletrico": "ELECTRIC", "ev": "ELECTRIC",
    "híbrido": "HYBRID", "hibrido": "HYBRID", "hybrid": "HYBRID",
    "gnv": "OTHER",
}

# Câmbio (palavra na versão) -> transmission (enum Meta): AUTOMATIC, MANUAL, OTHER
TRANSMISSION_MAP = {
    "aut": "AUTOMATIC", "aut.": "AUTOMATIC", "automático": "AUTOMATIC",
    "automatico": "AUTOMATIC", "automática": "AUTOMATIC", "cvt": "AUTOMATIC",
    "tiptronic": "AUTOMATIC", "s tronic": "AUTOMATIC", "dsg": "AUTOMATIC",
    "automatizado": "AUTOMATIC",
    "mec": "MANUAL", "mec.": "MANUAL", "manual": "MANUAL", "mecânico": "MANUAL",
    "mecanico": "MANUAL",
}

# Vocabulário de cores (pt-br) usado pra validar/limpar a cor vinda do site
KNOWN_COLORS = [
    "branco", "preto", "prata", "cinza", "vermelho", "azul", "verde",
    "amarelo", "marrom", "bege", "dourado", "vinho", "laranja", "bronze",
    "champagne", "grafite", "fumê", "fume", "rosa", "roxo", "gelo",
]
