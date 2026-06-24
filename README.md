# Feed do catálogo Meta Ads — Thiago Veículos

Automação que lê o estoque do site da **Thiago Veículos**
(https://thiagoveiculosrv.com.br) **uma vez por dia** e gera um arquivo
`catalog_vehicles.csv` no formato que o **catálogo do Meta Ads** entende.

O GitHub Actions roda o robô sozinho, publica o CSV no GitHub Pages e te dá um
**link fixo**. Você cadastra esse link uma única vez na Meta como **fonte de
dados agendada** — e nunca mais precisa mexer. Carro que vende sai do site, sai
do feed e a Meta marca como indisponível automaticamente.

```
site do Thiago  →  scraper.py (GitHub Actions, 1x/dia)  →  catalog_vehicles.csv  →  Meta
```

---

## O que cada arquivo faz

| Arquivo | Pra que serve |
|---|---|
| `config.py` | **O único que você edita.** Endereço, coordenadas, textos e os "de-para". |
| `scraper.py` | O robô. Lê o estoque, abre cada veículo e monta o CSV. |
| `requirements.txt` | Bibliotecas que o robô usa. |
| `.github/workflows/feed.yml` | O agendamento (roda todo dia + botão manual). |
| `docs/catalog_vehicles.csv` | **O feed.** É o que você aponta na Meta (gerado na 1ª execução). |
| `docs/index.html` | Uma pagininha com status do feed (gerada automática). |
| `test_parse.py` | Teste interno (não precisa rodar, mas não atrapalha). |

---

## Passo a passo (15 min, uma vez só)

### 1. Criar o repositório
1. No GitHub, clique em **New repository**.
2. Nome à sua escolha (ex.: `thiago-feed-meta`). Pode deixar **público** ou **privado** — o GitHub Pages funciona nos dois com conta normal.
3. Crie o repositório vazio.

### 2. Subir os arquivos
Jeito fácil (sem terminal): na página do repo → **Add file → Upload files** →
arraste **todos os arquivos e pastas** desta entrega (incluindo a pasta
`.github` e a pasta `docs`) → **Commit changes**.

> ⚠️ A pasta `.github` às vezes "some" ao arrastar no Windows porque começa com
> ponto. Se isso acontecer, crie o arquivo manualmente: **Add file → Create new
> file**, digite o caminho `.github/workflows/feed.yml` e cole o conteúdo.

### 3. Ligar o GitHub Pages (é ele que gera o link)
1. No repo: **Settings → Pages**.
2. Em **Source**, escolha **Deploy from a branch**.
3. Em **Branch**, selecione **main** e a pasta **/docs**. Clique em **Save**.
4. O seu link vai ser:
   ```
   https://SEU-USUARIO.github.io/NOME-DO-REPO/catalog_vehicles.csv
   ```

### 4. Rodar uma vez na mão (pra gerar o primeiro CSV)
1. Aba **Actions** → se aparecer um aviso pedindo pra habilitar, clique em **I understand my workflows, go ahead and enable them**.
2. Clique no workflow **“Atualizar feed Meta (Thiago Veículos)”** → botão **Run workflow** → **Run workflow** (verde).
3. Espere ~1–2 min. Quando ficar verde, abra o link do passo 3 no navegador: o CSV vai baixar/abrir. 

### 5. Cadastrar na Meta
1. **Gerenciador de Comércio** (business.facebook.com/commerce) → seu **catálogo** de veículos (ou crie um do tipo **Veículos**).
2. **Fontes de dados → Adicionar itens → Feed de dados → Agendado/Programado**.
3. Cole o link do CSV.
4. Frequência: **Diária** (pode pôr pra rodar de manhã, depois das 05:00, que é quando o robô já atualizou).
5. Salvar. A Meta vai ler o arquivo e importar os veículos.

Pronto. Daqui pra frente é automático nos dois lados.

---

## ⚠️ Dois ajustes que valem a pena (opcionais, mas recomendo)

**1. Latitude e longitude exatas da loja.**
No `config.py` eu deixei o centro de Rio Verde como ponto de partida. Pra deixar
certinho (ajuda no alcance dos anúncios por localização):
- Abra o Google Maps, ache a Thiago Veículos.
- Clique com o botão direito **em cima da loja** → o primeiro item do menu são as duas coordenadas. Clique pra copiar.
- Cole no `config.py`:
  ```python
  LATITUDE = -17.xxxxx
  LONGITUDE = -50.xxxxx
  ```

**2. Conferir o endereço/CEP** no `config.py`, caso tenha mudado algo.

Depois de editar o `config.py`, é só dar **Commit** — na próxima execução já entra com os valores novos. Se quiser aplicar na hora, rode o workflow de novo na mão (passo 4).

---

## Perguntas rápidas

**Quanto custa?** Nada. GitHub Actions e Pages são gratuitos nesse volume.

**E se o site mudar e quebrar o robô?** O scraper tem uma trava: se vier
**zero** veículo, ele **não** sobrescreve o feed (mantém o último bom) e a
execução falha de propósito, pra você perceber. Aí é só me chamar pra ajustar.

**Carro vendido continua aparecendo?** Não. Sumiu do site → some do feed na
atualização seguinte → a Meta marca como indisponível.

**Posso mudar o horário?** Sim, no `feed.yml`, na linha do `cron`. Hoje está
`0 8 * * *` (08:00 UTC = 05:00 de Brasília).

**Dá pra usar com mais de uma loja?** Dá — é só duplicar o repositório e trocar
o `config.py`. Cada loja vira um feed/link separado.

---

## Sobre os campos (pra referência)

O CSV traz **todos os 20 campos obrigatórios** da Meta + fotos (até 10 por
veículo) + 5 `custom_label` pra você segmentar campanhas:

- `custom_label_0` = faixa de preço (ex.: "80 a 120 mil")
- `custom_label_1` = carroceria (SUV, PICKUP, SEDAN…)
- `custom_label_2` = marca
- `custom_label_3` = ano
- `custom_label_4` = combustível

Isso deixa fácil criar conjuntos de produtos na Meta (ex.: "só SUV acima de 120
mil") sem ter que mexer no feed.
