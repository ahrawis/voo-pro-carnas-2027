# Voo pro Carnas 2027

Site do grupo que acompanha o preço da passagem **Porto Alegre → Rio** no feriado
de Carnaval de 2027. Atualiza sozinho, uma vez por dia.

- `public/index.html` — o site inteiro, num arquivo só. Lê `dados.json` e desenha.
- `public/dados.json` — preço de hoje, as quatro combinações e o histórico completo.
- `coleta.py` — pesquisa os preços no Google Flights (via a lib `flights`) e grava o JSON.
- `wrangler.jsonc` — diz ao Cloudflare que isto é site estático e que a pasta é `public/`.
- `.github/workflows/preco.yml` — roda a coleta todo dia às 09:00 e faz commit do resultado.

## A janela do grupo

Ninguém pode faltar ao trabalho, então a busca só aceita voo que:

- **sai de POA a partir das 17h de sexta 05/02** (depois do expediente);
- **pousa em POA até as 08:30 de quinta 11/02**.

Na prática sobram duas voltas: quarta 10/02 à noite, ou o voo que sai do Rio de
madrugada e pousa 07:40 de quinta. Não existe voo que chegue antes disso — por
isso o limite é 08:30 e não 07:00.

Destinos: Galeão (GIG) e Santos Dumont (SDU). São 2 destinos × 2 voltas = 4
buscas por dia, e o site mostra a mais barata em destaque e as outras três ao lado.

## Moeda

O Google responde na moeda de quem chamou — o runner do GitHub Actions fica nos
EUA e devolvia dólar. A coleta prende a busca em `hl=pt-BR&gl=BR&curr=BRL` e,
se mesmo assim vier outra moeda, descarta a leitura em vez de gravar. Um buraco
de um dia no gráfico é melhor que um R$ 290 que na verdade eram US$ 290.

## Rodando na mão

```bash
pip install flights==0.8.4
python coleta.py           # confere os preços e atualiza dados.json
python coleta.py --teste   # só os self-checks, sem rede
```

Pra ver o site local, precisa de um servidor (o `fetch` do `dados.json` não
funciona abrindo o arquivo direto):

```bash
python -m http.server 8777 --directory public
```

## Publicando no Cloudflare

O dashboard atual importa repositório como **Worker** (não como Pages), e Worker
só sobe site estático se existir um `wrangler.jsonc` — sem ele o deploy termina
"sem rotas ativas", que é exatamente o que aconteceu na primeira tentativa.

O `wrangler.jsonc` deste repo já resolve isso: declara `assets.directory` como
`public/` e liga o endereço `workers.dev`. Cada push republica sozinho.

Só `public/` vai pro ar. O `coleta.py`, o workflow e os rascunhos de design
ficam no repositório mas fora do site.

O GitHub Actions já vem configurado; a única coisa a conferir é
**Settings → Actions → General → Workflow permissions → Read and write**, senão
o robô não consegue fazer commit.

## Se o preço parar de atualizar

O Google às vezes devolve HTTP 429 pra IP de datacenter. Se os runs do Actions
começarem a falhar, o plano B é rodar `coleta.py` na sua máquina (que já roda o
fli) e dar push do `dados.json` — o site não muda em nada.
