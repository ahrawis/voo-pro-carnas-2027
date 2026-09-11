"""Coleta diaria do preco POA -> Rio no feriado de Carnaval 2027.

Roda uma vez por dia (GitHub Actions ou cron local), pesquisa todas as
combinacoes de destino x data de volta que cabem na janela do grupo, e grava o
resultado em dados.json -- que e o unico arquivo que o site le.

Janela do grupo (ninguem pode faltar ao trabalho):
  - ida: sexta 05/02/2027, partindo de POA das 17h em diante
  - volta: precisa pousar em POA ate as 8h30 de quinta 11/02 -- ou seja, voo de
    quarta a noite, ou o red-eye que sai do Rio de madrugada

Uso:
    python coleta.py            # coleta e grava dados.json
    python coleta.py --teste    # roda os self-checks, sem rede
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

DADOS = Path(__file__).parent / "dados.json"
FUSO_BR = timezone(timedelta(hours=-3))

IDA = "2027-02-05"
IDA_A_PARTIR_DE = 17  # hora local em POA
DESTINOS = ["GIG", "SDU"]
# (data da volta, hora minima de partida, hora maxima de chegada em POA)
VOLTAS = [
    ("2027-02-10", 19, None),  # quarta a noite
    ("2027-02-11", None, 9),   # red-eye de quinta; o corte fino fica em cabe_na_janela
]
# Regra que manda de verdade: tem que pousar em POA a tempo de trabalhar quinta.
# 08:30 nao e um numero redondo a toa -- o voo mais cedo do Rio pousa 07:40
# (GIG 05:30, direto) e o seguinte 08:30. Cortar antes das 08:30 apaga a volta
# de quinta inteira e sobra so a de quarta a noite.
POUSO_LIMITE = datetime(2027, 2, 11, 8, 30)

# limiares do veredicto, em relacao ao historico da propria rota
MIN_LEITURAS = 10       # abaixo disso nao ha base para opinar
FOLGA_COMPRAR = 1.08    # ate 8% acima do minimo historico = compra
MIRA_JUSTO = 0.90       # ate 90% do caminho entre minimo e media = justo


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


def _link(destino: str, volta: str) -> str:
    return (
        "https://www.google.com/travel/flights?q="
        "Flights%20to%20{}%20from%20POA%20on%20{}%20through%20{}".format(destino, IDA, volta)
    )


def cabe_na_janela(ida_voo, volta_voo) -> bool:
    """A regra do grupo: sai depois do expediente de sexta, pousa a tempo de quinta.

    Os filtros do Google sao por hora cheia e as vezes escapam (ja voltou voo das
    06:50 pousando 11:00), entao a decisao final e sempre aqui.
    """
    if ida_voo.legs[0].departure_datetime.hour < IDA_A_PARTIR_DE:
        return False
    return volta_voo.legs[-1].arrival_datetime <= POUSO_LIMITE


def buscar_combinacao(destino: str, volta: str, cedo: Optional[int], tarde: Optional[int]) -> Optional[Dict]:
    """Busca a passagem mais barata de uma combinacao destino x data de volta."""
    from fli.models import (
        Airport, FlightSearchFilters, FlightSegment, PassengerInfo,
        SeatType, SortBy, TimeRestrictions, TripType,
    )
    from fli.search import SearchFlights

    origem, chegada = Airport.POA, getattr(Airport, destino)
    segmentos = [
        FlightSegment(
            departure_airport=[[origem, 0]],
            arrival_airport=[[chegada, 0]],
            travel_date=IDA,
            time_restrictions=TimeRestrictions(earliest_departure=IDA_A_PARTIR_DE),
        ),
        FlightSegment(
            departure_airport=[[chegada, 0]],
            arrival_airport=[[origem, 0]],
            travel_date=volta,
            time_restrictions=TimeRestrictions(earliest_departure=cedo, latest_arrival=tarde),
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
        if not cabe_na_janela(ida_voo, volta_voo):
            continue
        preco = volta_voo.price  # no round-trip, a volta carrega o total da combinacao
        if melhor is None or preco < melhor["preco"]:
            melhor = {
                "preco": round(preco, 2),
                "moeda": volta_voo.currency or "BRL",
                "destino": destino,
                "ida": _trecho(ida_voo),
                "volta": _trecho(volta_voo),
                "link": _link(destino, volta),
            }
    return melhor


def coletar() -> List[Dict]:
    """Varre todas as combinacoes da janela. Uma falha nao derruba as outras."""
    achados = []
    for destino in DESTINOS:
        for volta, cedo, tarde in VOLTAS:
            try:
                achado = buscar_combinacao(destino, volta, cedo, tarde)
            except Exception as erro:  # noqa: BLE001 - um destino fora nao invalida o dia
                print("falhou {} volta {}: {}".format(destino, volta, erro), file=sys.stderr)
                continue
            if achado:
                achados.append(achado)
                print("{} volta {}: R$ {:.2f}".format(destino, volta, achado["preco"]))
            else:
                print("{} volta {}: sem resultado na janela".format(destino, volta))
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

    menor, maior = min(precos), max(precos)
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
        "atual": melhor,
        "combinacoes": sorted(
            [{"destino": a["destino"], "volta": a["volta"]["data"], "preco": a["preco"]} for a in achados],
            key=lambda c: c["preco"],
        ),
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


def testes() -> None:
    """Self-check da logica que nao depende de rede."""
    base = [{"data": "2026-01-{:02d}".format(i + 1), "preco": p}
            for i, p in enumerate([2000, 2200, 2400, 2600, 1800, 2100, 2300, 2500, 2700, 2900])]

    assert veredicto(1850, base)["codigo"] == "comprar", "colado no minimo = comprar"
    assert veredicto(2900, base)["codigo"] == "esperar", "acima da media = esperar"
    assert veredicto(2150, base)["codigo"] == "justo", "abaixo da media = justo"
    assert veredicto(1800, base[:3])["codigo"] == "calibrando", "historico curto nao opina"

    # a janela do grupo: sai depois do expediente de sexta, pousa antes da quinta de manha
    class _Voo:
        def __init__(self, partida, chegada):
            trecho = type("T", (), {"departure_datetime": partida, "arrival_datetime": chegada})
            self.legs = [trecho]

    sexta_noite = _Voo(datetime(2027, 2, 5, 17, 25), datetime(2027, 2, 5, 19, 20))
    sexta_tarde = _Voo(datetime(2027, 2, 5, 14, 10), datetime(2027, 2, 5, 16, 5))
    madrugada = _Voo(datetime(2027, 2, 11, 2, 30), datetime(2027, 2, 11, 4, 45))
    quarta_noite = _Voo(datetime(2027, 2, 10, 21, 15), datetime(2027, 2, 10, 23, 25))
    red_eye = _Voo(datetime(2027, 2, 11, 5, 30), datetime(2027, 2, 11, 7, 40))
    manha_quinta = _Voo(datetime(2027, 2, 11, 6, 50), datetime(2027, 2, 11, 11, 0))

    assert cabe_na_janela(sexta_noite, madrugada), "madrugada de quinta cabe"
    assert cabe_na_janela(sexta_noite, quarta_noite), "quarta a noite cabe"
    assert cabe_na_janela(sexta_noite, red_eye), "o voo das 05:30 pousando 07:40 cabe"
    assert not cabe_na_janela(sexta_tarde, madrugada), "ida antes das 17h faz faltar sexta"
    assert not cabe_na_janela(sexta_noite, manha_quinta), "pouso 11h faz faltar quinta"

    achados = [
        {"preco": 1900.0, "moeda": "BRL", "destino": "SDU", "link": "x",
         "ida": {"data": IDA, "partida": "18:40"}, "volta": {"data": "2027-02-11"}},
        {"preco": 1476.0, "moeda": "BRL", "destino": "GIG", "link": "x",
         "ida": {"data": IDA, "partida": "17:25"}, "volta": {"data": "2027-02-10"}},
    ]
    agora = datetime(2026, 9, 10, 9, 0, tzinfo=FUSO_BR)
    saida = montar(achados, {"historico": [{"data": "2026-09-09", "preco": 1600.0}]}, agora)
    assert saida["atual"]["preco"] == 1476.0, "o mais barato entre as combinacoes vence"
    assert saida["resumo"]["menor"] == 1476.0
    assert saida["resumo"]["leituras"] == 2
    assert saida["combinacoes"][0]["destino"] == "GIG", "combinacoes saem da mais barata pra mais cara"
    assert saida["embarque"] == "2027-02-05T17:25:00-03:00"

    # rodar duas vezes no mesmo dia substitui a leitura, nao duplica
    denovo = montar(achados, saida, agora)
    assert denovo["resumo"]["leituras"] == 2, "uma leitura por dia"

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
    dados = montar(achados, anterior, datetime.now(FUSO_BR))
    DADOS.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    print("gravado: R$ {:.2f} ({}) -- {}".format(
        dados["atual"]["preco"], dados["atual"]["destino"], dados["veredicto"]["titulo"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
