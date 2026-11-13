"""Coleta diaria do preco POA -> Maringa no reveillon 2026/2027.

Roda uma vez por dia (GitHub Actions), varre todas as combinacoes de ida x volta
da janela do reveillon, grava o resultado em public/dados.json -- que e o unico
arquivo que o site le -- e manda e-mail quando o preco bate um minimo historico.

Janela: ida 28, 29 ou 30/12; volta 01, 02, 03 ou 04/01. Sao 12 combinacoes.

Uso:
    python coleta.py            # coleta, grava e alerta se bateu minimo
    python coleta.py --teste    # roda os self-checks, sem rede e sem e-mail
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional

DADOS = Path(__file__).parent / "public" / "dados.json"
FUSO_BR = timezone(timedelta(hours=-3))

DESTINOS = ["MGF"]
IDAS = ["2026-12-28", "2026-12-29", "2026-12-30"]
VOLTAS = ["2027-01-01", "2027-01-02", "2027-01-03", "2027-01-04"]

MOEDA = "BRL"
# O Google responde na moeda de quem chamou: do runner americano do GitHub
# Actions vinha USD, e um R$ 290 falso entrou no historico. Estes parametros
# prendem a resposta em real, rode de onde rodar.
REGIAO = "?hl=pt-BR&gl=BR&curr=BRL"

# limiares do veredicto, em relacao ao historico da propria rota
MIN_LEITURAS = 10       # abaixo disso nao ha base para opinar
FOLGA_COMPRAR = 1.08    # ate 8% acima do minimo historico = compra
MIRA_JUSTO = 0.90       # ate 90% do caminho entre minimo e media = justo

SITE = "https://voo-pro-carnas-2027.lucasluvisonpoa.workers.dev"


def prender_em_reais() -> None:
    """Prega a regiao brasileira na URL de busca. Idempotente."""
    from fli.search.flights import SearchFlights

    if REGIAO not in SearchFlights.BASE_URL:
        SearchFlights.BASE_URL += REGIAO


def conferir_moeda(moeda: Optional[str]) -> None:
    """Um preco em moeda errada e pior que preco nenhum -- ele suja o historico."""
    if (moeda or MOEDA) != MOEDA:
        raise RuntimeError(
            "Google respondeu em {}, nao em {}. Leitura descartada.".format(moeda, MOEDA)
        )


def _hora(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _trecho(voo) -> Dict:
    """Achata um FlightResult em algo que o site consegue desenhar."""
    primeira, ultima = voo.legs[0], voo.legs[-1]
    return {
        "data": primeira.departure_datetime.strftime("%Y-%m-%d"),
        "partida": _hora(primeira.departure_datetime),
        "chegada": _hora(ultima.arrival_datetime),
        "chega_em": ultima.arrival_datetime.strftime("%Y-%m-%d"),
        "cia": primeira.airline.value,
        "voo": "{} {}".format(primeira.airline.name, primeira.flight_number),
        "paradas": voo.stops,
        "duracao": voo.duration,
    }


def _link(destino: str, ida: str, volta: str) -> str:
    return (
        "https://www.google.com/travel/flights?q="
        "Flights%20to%20{}%20from%20POA%20on%20{}%20through%20{}".format(destino, ida, volta)
    )


def buscar_combinacao(destino: str, ida: str, volta: str) -> Optional[Dict]:
    """Busca a passagem mais barata de uma combinacao destino x ida x volta."""
    from fli.models import (
        Airport, FlightSearchFilters, FlightSegment, PassengerInfo,
        SeatType, SortBy, TripType,
    )
    from fli.search import SearchFlights

    prender_em_reais()
    origem, chegada = Airport.POA, getattr(Airport, destino)
    segmentos = [
        FlightSegment(
            departure_airport=[[origem, 0]],
            arrival_airport=[[chegada, 0]],
            travel_date=ida,
        ),
        FlightSegment(
            departure_airport=[[chegada, 0]],
            arrival_airport=[[origem, 0]],
            travel_date=volta,
        ),
    ]
    filtros = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segmentos,
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
        show_all_results=False,
    )

    resultados = SearchFlights().search(filtros, top_n=5) or []
    melhor = None
    for item in resultados:
        partes = item if isinstance(item, tuple) else (item,)
        if len(partes) < 2:
            continue  # so faz sentido com ida e volta
        ida_voo, volta_voo = partes[0], partes[-1]
        conferir_moeda(volta_voo.currency)
        preco = volta_voo.price  # no round-trip, a volta carrega o total da combinacao
        if melhor is None or preco < melhor["preco"]:
            melhor = {
                "preco": round(preco, 2),
                "moeda": volta_voo.currency or MOEDA,
                "destino": destino,
                "ida": _trecho(ida_voo),
                "volta": _trecho(volta_voo),
                "link": _link(destino, ida, volta),
            }
    return melhor


def coletar() -> List[Dict]:
    """Varre a janela inteira. Uma combinacao falha nao derruba as outras."""
    achados = []
    for destino in DESTINOS:
        for ida in IDAS:
            for volta in VOLTAS:
                try:
                    achado = buscar_combinacao(destino, ida, volta)
                except Exception as erro:  # noqa: BLE001 - uma data fora nao invalida o dia
                    print("falhou {} {} a {}: {}".format(destino, ida, volta, erro), file=sys.stderr)
                    continue
                if achado:
                    achados.append(achado)
                    print("{} {} a {}: R$ {:.2f}".format(destino, ida, volta, achado["preco"]))
                else:
                    print("{} {} a {}: sem resultado".format(destino, ida, volta))
    return achados


def veredicto(preco: float, historico: List[Dict]) -> Dict:
    """Traduz o preco de hoje em 'esperar' / 'preco justo' / 'comprar agora'."""
    precos = [p["preco"] for p in historico]
    if len(precos) < MIN_LEITURAS:
        return {
            "codigo": "calibrando",
            "titulo": "Calibrando",
            "nota": "faltam {} leituras pra base de comparação ficar honesta".format(
                MIN_LEITURAS - len(precos)
            ),
        }

    menor = min(precos)
    media = sum(precos) / len(precos)

    if preco <= menor * FOLGA_COMPRAR:
        return {"codigo": "comprar", "titulo": "Comprar agora!",
                "nota": "tá colado no menor preço que já apareceu. Não espera passar."}
    if preco <= menor + (media - menor) * MIRA_JUSTO:
        return {"codigo": "justo", "titulo": "Preço justo",
                "nota": "abaixo da média da rota. Quem precisa de garantia pode fechar."}
    return {"codigo": "esperar", "titulo": "Esperar",
            "nota": "acima da média. Já caiu mais barato que isso em {} das leituras.".format(
                sum(1 for p in precos if p < preco))}


def combinacoes(achados: List[Dict]) -> List[Dict]:
    """Uma linha por par ida x volta, da mais barata pra mais cara."""
    return sorted(
        [{
            "destino": a["destino"],
            "ida": a["ida"]["data"],
            "volta": a["volta"]["data"],
            "paradas": max(a["ida"]["paradas"], a["volta"]["paradas"]),
            "preco": a["preco"],
        } for a in achados],
        key=lambda c: c["preco"],
    )


def montar(achados: List[Dict], anterior: Dict, agora: datetime) -> Dict:
    """Monta o dados.json novo a partir da coleta de hoje e do arquivo anterior."""
    hoje = agora.strftime("%Y-%m-%d")
    historico = [h for h in anterior.get("historico", []) if h["data"] != hoje]

    melhor = min(achados, key=lambda a: a["preco"])
    historico.append({"data": hoje, "preco": melhor["preco"]})
    historico.sort(key=lambda h: h["data"])

    precos = [h["preco"] for h in historico]
    return {
        "atualizado_em": agora.isoformat(timespec="seconds"),
        "moeda": melhor["moeda"],
        "embarque": "{}T{}:00-03:00".format(melhor["ida"]["data"], melhor["ida"]["partida"]),
        "reveillon": "2026-12-31T23:59:00-03:00",
        "atual": melhor,
        "combinacoes": combinacoes(achados),
        "janela": {"idas": IDAS, "voltas": VOLTAS},
        "resumo": {
            "menor": min(precos),
            "maior": max(precos),
            "media": round(sum(precos) / len(precos), 2),
            "leituras": len(precos),
            "menor_em": min(historico, key=lambda h: h["preco"])["data"],
        },
        "veredicto": veredicto(melhor["preco"], historico),
        "historico": historico,
    }


def minimo_anterior(anterior: Dict, hoje: str) -> Optional[float]:
    """Menor preco ja visto antes de hoje. None quando nao ha com que comparar."""
    passado = [h["preco"] for h in anterior.get("historico", []) if h["data"] != hoje]
    return min(passado) if passado else None


def alertar(dados: Dict, prev_min: float) -> bool:
    """Manda e-mail de queda. Devolve False quando o SMTP nao esta configurado."""
    usuario = os.getenv("SMTP_USER", "")
    senha = os.getenv("SMTP_PASSWORD", "")
    destino = os.getenv("ALERTA_PARA", "") or usuario
    if not usuario or not senha or not destino:
        print("SMTP não configurado — alerta não enviado", file=sys.stderr)
        return False

    atual = dados["atual"]
    queda = prev_min - atual["preco"]
    corpo = (
        "O voo pro réveillon em Maringá bateu o menor preço desde que o robô começou a olhar.\n\n"
        "Agora:           R$ {:.2f}\n"
        "Mínimo anterior: R$ {:.2f}   (queda de R$ {:.2f})\n\n"
        "Ida:   {} às {}, {} ({})\n"
        "Volta: {} às {}, {} ({})\n\n"
        "Ver no site:          {}\n"
        "Ver no Google Flights: {}\n"
    ).format(
        atual["preco"], prev_min, queda,
        atual["ida"]["data"], atual["ida"]["partida"],
        _paradas_texto(atual["ida"]["paradas"]), atual["ida"]["cia"],
        atual["volta"]["data"], atual["volta"]["partida"],
        _paradas_texto(atual["volta"]["paradas"]), atual["volta"]["cia"],
        SITE, atual["link"],
    )

    msg = MIMEText(corpo, "plain", "utf-8")
    msg["Subject"] = "Réveillon em Maringá: R$ {:.0f}, menor preço até agora".format(atual["preco"])
    msg["From"] = usuario
    msg["To"] = destino

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                      int(os.getenv("SMTP_PORT", "587")), timeout=30) as servidor:
        servidor.starttls()
        servidor.login(usuario, senha)
        servidor.send_message(msg)
    print("alerta enviado para {}".format(destino))
    return True


def _paradas_texto(n: int) -> str:
    return "direto" if n == 0 else "1 parada" if n == 1 else "{} paradas".format(n)


def testes() -> None:
    """Self-check da logica que nao depende de rede."""
    base = [{"data": "2026-11-{:02d}".format(i + 1), "preco": p}
            for i, p in enumerate([2000, 2200, 2400, 2600, 1800, 2100, 2300, 2500, 2700, 2900])]

    assert veredicto(1850, base)["codigo"] == "comprar", "colado no minimo = comprar"
    assert veredicto(2900, base)["codigo"] == "esperar", "acima da media = esperar"
    assert veredicto(2150, base)["codigo"] == "justo", "abaixo da media = justo"
    assert veredicto(1800, base[:3])["codigo"] == "calibrando", "historico curto nao opina"

    conferir_moeda("BRL")
    conferir_moeda(None)
    for ruim in ("USD", "EUR"):
        try:
            conferir_moeda(ruim)
        except RuntimeError:
            pass
        else:
            raise AssertionError("{} passou pela trava de moeda".format(ruim))

    def _achado(preco, ida_data, volta_data):
        return {"preco": preco, "moeda": "BRL", "destino": "MGF", "link": "x",
                "ida": {"data": ida_data, "partida": "07:10", "paradas": 1},
                "volta": {"data": volta_data, "partida": "19:40", "paradas": 1}}

    achados = [
        _achado(1900.0, "2026-12-28", "2027-01-04"),
        _achado(1420.0, "2026-12-30", "2027-01-02"),
        _achado(1655.0, "2026-12-29", "2027-01-01"),
    ]

    opcoes = combinacoes(achados)
    assert [o["preco"] for o in opcoes] == [1420.0, 1655.0, 1900.0], "ordena da mais barata"
    assert opcoes[0]["ida"] == "2026-12-30" and opcoes[0]["volta"] == "2027-01-02"

    agora = datetime(2026, 11, 13, 9, 0, tzinfo=FUSO_BR)
    saida = montar(achados, {"historico": [{"data": "2026-11-12", "preco": 1600.0}]}, agora)
    assert saida["atual"]["preco"] == 1420.0, "a combinacao mais barata vence"
    assert saida["resumo"]["menor"] == 1420.0
    assert saida["resumo"]["leituras"] == 2
    assert saida["embarque"] == "2026-12-30T07:10:00-03:00"
    assert saida["janela"]["idas"] == IDAS

    # rodar duas vezes no mesmo dia substitui a leitura, nao duplica
    denovo = montar(achados, saida, agora)
    assert denovo["resumo"]["leituras"] == 2, "uma leitura por dia"

    # o alerta compara com o passado, nunca com a leitura de hoje
    anterior = {"historico": [{"data": "2026-11-12", "preco": 1600.0},
                              {"data": "2026-11-13", "preco": 1420.0}]}
    assert minimo_anterior(anterior, "2026-11-13") == 1600.0, "ignora a leitura de hoje"
    assert minimo_anterior({"historico": []}, "2026-11-13") is None, "sem passado, sem alerta"
    assert minimo_anterior({}, "2026-11-13") is None, "rota nova nao dispara e-mail"

    print("testes ok")


def main() -> int:
    if "--teste" in sys.argv:
        testes()
        return 0

    achados = coletar()
    if not achados:
        print("nenhuma combinacao retornou preco -- dados.json mantido como esta", file=sys.stderr)
        return 1

    anterior = json.loads(DADOS.read_text(encoding="utf-8")) if DADOS.exists() else {}
    agora = datetime.now(FUSO_BR)
    prev_min = minimo_anterior(anterior, agora.strftime("%Y-%m-%d"))

    dados = montar(achados, anterior, agora)
    DADOS.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    print("gravado: R$ {:.2f} ({} a {}) -- {}".format(
        dados["atual"]["preco"], dados["atual"]["ida"]["data"],
        dados["atual"]["volta"]["data"], dados["veredicto"]["titulo"]))

    if prev_min is not None and dados["atual"]["preco"] < prev_min:
        print("novo minimo: R$ {:.2f} (antes R$ {:.2f})".format(dados["atual"]["preco"], prev_min))
        try:
            alertar(dados, prev_min)
        except Exception as erro:  # noqa: BLE001 - e-mail falho nao pode perder o preco do dia
            print("alerta falhou: {}".format(erro), file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
