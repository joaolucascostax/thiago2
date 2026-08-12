# Por que o feed não estava batendo 1:1

Conferi o repositório contra o site ao vivo em 11/08/2026. O problema não é um
só — são cinco, e o mais grave não é o de contagem: **12% dos veículos estavam
com o preço de outro carro.**

---

## 1. Preço vazando do carrossel de sugestões — o mais grave

O `scraper.py` pegava o preço assim: primeiro lia a meta tag
`product:price:amount` (que está certa), e **depois** varria a página inteira
procurando `de R$ X ... por R$ Y` e sobrescrevia.

O problema é que a página de veículo termina com o bloco **"Sugestões para
você"**, com outros três carros da loja. Quando o carro principal não tem
promoção (a maioria), o primeiro `de/por` que a regex encontra é o de um carro
**da sugestão**. E o preço daquele carro ia pro feed.

Resultado no CSV que está publicado agora:

- **16 veículos com R$ 114.990 exatos** — um Civic, uma Toro, uma Hilux, duas
  Saveiro, três Strada, quatro S10… todos com o mesmo preço. Impossível.
- **5 veículos com "de R$ 119.990 por R$ 115.990"** — um L200, um T-Cross, uma
  Land Rover Discovery, um Compass e um Nivus. Todos idênticos. Impossível.

Amostra de 50 carros conferida contra o site, um por um:

| Veículo | Preço no site | Preço no feed |
|---|---|---|
| VW Saveiro Trooper 1.6 (1080354) | R$ 44.990 | **R$ 114.990** |
| Fiat Strada Endurance CS Plus (1082661) | R$ 84.990 | **R$ 114.990** |
| Chevrolet S10 Colina 2.8 (1082303) | R$ 67.990 | **R$ 114.990** |
| Fiat Strada Freedom 1.4 CD (1068299) | R$ 74.990 | **R$ 114.990** |
| Toyota Hilux SRX 2.8 (1080742) | R$ 175.990 | **R$ 114.990** |

Uma Saveiro de R$ 44.990 anunciada por R$ 114.990. Uma Hilux de R$ 175.990
anunciada por R$ 114.990. Isso queima verba e mata a conversão.

**Correção:** o preço agora vem **só** da meta tag `product:price:amount`, que é
por página e não mente. O `de/por` só é considerado dentro da região do próprio
veículo (o HTML antes de "Sugestões") e só é aceito se o "por" bater com a meta
tag.

Reproduzi o bug em teste controlado — mesma página, os dois scrapers:

```
v1 (atual):  price = 114990.0    <- preço de outro carro
v2 (novo):   price = 34990.0     <- correto
```

---

## 2. A paginação estava pulando veículos

O `config.py` pedia `registros_por_pagina=60`. **O site não aceita esse valor.**
Ele força 18 e faz um redirect que remapeia o número da página:

```
pedido: /estoque?registros_por_pagina=60&pagina=2
chegou: /estoque?pagina=9&registros_por_pagina=18

pedido: /estoque?registros_por_pagina=60&pagina=4
chegou: /estoque?pagina=10&registros_por_pagina=18
```

Ou seja: o robô achava que estava andando página a página, mas estava sendo
jogado pra páginas aleatórias. Somando isso ao `if new_in_page == 0: break`
(que corta o laço na primeira página repetida), a cobertura virava sorte.

Hoje o site diz **175 veículos**; o feed tem **174**. O que faltou foi o
**VW Golf Highline 1.4 TSI (id 1083824, R$ 84.990)**.

**Correção:** `PAGE_SIZE = 18` e o número de páginas vem do próprio site.

---

## 3. A trava de segurança nunca funcionou

O `feed_stats.json` publicado mostra `"veiculos_no_site": null`. A regex
procurava `175 veículos encontrados` no HTML cru, mas no HTML o número vem
dentro de uma tag: `<strong>175</strong> veículos encontrados`. Nunca casava.

Consequência: a única verificação de integridade do robô estava morta desde o
primeiro dia. Ele podia trazer 60 carros de 175 e publicar sorrindo.

**Correção:** a contagem é lida do **texto** da página, e agora, se o número não
bater, o robô falha e **não sobrescreve** o feed bom.

---

## 4. Câmbio em branco em quase metade do catálogo

`transmission` vazio em **82 de 174** (47%) e `fuel_type` vazio em 22.

O robô tentava adivinhar pelo nome da versão. Versões como
"Gol 1.0 Flex 12V 5p" ou "ARGO DRIVE 1.0 6V Flex" simplesmente não trazem o
câmbio no nome — mas a informação **está na página**, em dois lugares:

- a `<title>`: `... 8V 4p Flex 4 portas, câmbio Manual em Rio Verde`
- a ficha técnica: `Manual · 2012/2013 · 171.007 km · Branco · 4 portas`

**Correção:** lê da `<title>` (formato fixo, confiável) e cai pra ficha técnica.

---

## 5. Quilometragem grudando números

A regex de km era `km\s*[:\-]?\s*([\d.\s]+)\s*km` — com `\s` **dentro** da
classe de caracteres, ela atravessa espaços e cola números de blocos diferentes.
No feed atual tem uma F-350 com **3.388.099 km**.

**Correção:** regex sem `\s` na classe, lendo do bloco "+ Informações"
(`KM: 171007 km`) e caindo pra ficha técnica.

---

## Bônus: coisas erradas no cadastro do site (não é o robô)

Sete veículos estão cadastrados **no site** com carroceria "Conversível/Cupê"
sem ser: o Gol 4p, uma Ranger, uma S10, um Voyage, um Corolla, um HB20 e uma
F-250. O robô estava copiando corretamente — a origem é que está errada.

Isso atrapalha os conjuntos de produtos na Meta e os filtros do próprio site.

**O que fiz:** quando o modelo é claramente picape/SUV/moto e o site diz outra
coisa, o feed usa o valor certo e registra o caso em `docs/divergencias.json`.
**O que você tem que fazer:** pedir pro pessoal da loja corrigir no Autoconf.

Um detalhe que também vale checar com eles: a Ford F-350 (id 1015593) está com
3.388.099 km e outra com 511.456 km no cadastro.

---

## Limite que continua existindo

**Só dá pra pegar 5 fotos por veículo.** O site entrega 5 no HTML; o resto fica
atrás do botão "Ver todas as fotos", que carrega por JavaScript. Por isso as
colunas `image[5]` a `image[9]` estão vazias em 100% das linhas.

Pra resolver de verdade precisaria descobrir o endpoint que o modal chama, ou
rodar um navegador headless no Actions. Dá pra fazer — me fala se quer que eu
vá atrás.

---

## O que mudou nos arquivos

| Arquivo | O que fazer |
|---|---|
| `scraper.py` | substituir inteiro |
| `config.py` | substituir inteiro (`PAGE_SIZE` 60 → 18, `DIAS_FORA_DE_ESTOQUE`, carrocerias novas) |
| `.github/workflows/feed.yml` | substituir inteiro (roda de 3/3h, confere o CSV, tirei a gambiarra da coluna `id`) |
| `test_parse.py` | substituir inteiro (o antigo testava um HTML inventado que não parece com o do site — por isso passava enquanto a produção quebrava) |

Depois de subir: **Actions → Run workflow** pra gerar o CSV novo na hora, e
confira `docs/feed_stats.json`. Tem que aparecer
`"bate_com_o_site": true` e `"veiculos_no_site": 175`.

Na Meta, como os preços de 21 veículos vão mudar de uma vez, vale forçar uma
sincronização manual da fonte de dados logo depois em vez de esperar o
agendamento.

---

## Duas coisas que mudei de comportamento (avise se preferir diferente)

1. **Carro vendido agora fica 3 dias no feed como `out of stock`** em vez de
   sumir. A Meta pausa o anúncio na hora e o item não perde histórico.
   Pra desligar: `DIAS_FORA_DE_ESTOQUE = 0` no `config.py`.
2. **Roda de 3 em 3 horas** em vez de 1x/dia. Se preferir voltar, é a linha do
   `cron` no `feed.yml`.
