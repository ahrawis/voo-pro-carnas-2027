# Voo pro Réveillon em Maringá

Acompanha o preço da passagem **Porto Alegre → Maringá** no réveillon 2026/2027.
Atualiza sozinho uma vez por dia e manda e-mail quando bate o menor preço.

- `public/index.html` — o site inteiro, num arquivo só. Lê `dados.json` e desenha.
- `public/dados.json` — preço de hoje, as 12 combinações de data e o histórico.
- `coleta.py` — busca no Google Flights (via a lib `flights`), grava o JSON e alerta.
- `wrangler.jsonc` — diz ao Cloudflare que isto é site estático e que a pasta é `public/`.
- `.github/workflows/preco.yml` — roda a coleta todo dia às 09:00 e faz commit do resultado.
- `arquivo/` — o site e os 63 dias de preço do Carnaval 2027, aposentado em 13/11/2026.

## A janela

Ida em 28, 29 ou 30/12; volta em 01, 02, 03 ou 04/01. São 12 combinações por dia,
e o site mostra todas numa grade: a linha é quando você sai, a coluna é quando volta.
A mais barata fica em destaque.

## Alerta por e-mail

Dispara só quando o preço do dia fica **abaixo de tudo que já foi registrado**.
Nunca dispara na primeira leitura de uma rota, porque não há com que comparar.

Precisa de três secrets no repositório (Settings → Secrets and variables → Actions):

| secret | o que é |
|---|---|
| `SMTP_USER` | o endereço que envia, ex. `voce@gmail.com` |
| `SMTP_PASSWORD` | **senha de app** do Gmail, nunca a senha da conta |
| `ALERTA_PARA` | para onde vai o alerta (se vazio, manda pro próprio `SMTP_USER`) |

Opcionais: `SMTP_HOST` (padrão `smtp.gmail.com`) e `SMTP_PORT` (padrão `587`).

Sem os secrets a coleta roda igual, só não manda e-mail.

## Moeda

O Google responde na moeda de quem chamou — o runner do GitHub Actions fica nos
EUA e devolvia dólar. A coleta prende a busca em `hl=pt-BR&gl=BR&curr=BRL` e,
se mesmo assim vier outra moeda, descarta a leitura em vez de gravar. Um buraco
de um dia no gráfico é melhor que um R$ 290 que na verdade eram US$ 290.

## Rodando na mão

```bash
pip install flights==0.8.4
python coleta.py           # confere os preços e atualiza dados.json
python coleta.py --teste   # só os self-checks, sem rede e sem e-mail
```

Pra ver o site local, precisa de um servidor (o `fetch` do `dados.json` não
funciona abrindo o arquivo direto):

```bash
python -m http.server 8777 --directory public
```

## Se o preço parar de atualizar

O Google devolve resposta vazia para IP que pesquisou demais — acontece na
máquina local depois de uma bateria de testes e passa em algumas horas. O runner
do GitHub usa outro IP e não costuma pegar o bloqueio. Se os runs do Actions
começarem a falhar, o plano B é rodar `coleta.py` na sua máquina e dar push do
`public/dados.json` — o site não muda em nada.

## Backlog

Ideias levantadas e ainda não feitas:

- Contador alternativo mirando a virada (31/12 23:59) em vez do embarque.
- Alerta também quando o preço cruzar um teto definido por você, não só em mínimo histórico.
- Incluir Londrina (LDB) como destino alternativo — fica a ~100 km de Maringá.
- Resumo semanal por e-mail com a tendência, além do alerta de queda.
- Marcar no gráfico o dia em que cada e-mail foi disparado.
