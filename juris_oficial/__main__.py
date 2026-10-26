# -*- coding: utf-8 -*-
"""Linha de comando (para quem não usa o MCP):

    python -m juris_oficial "\"acordo de não persecução penal\" e retroatividade" --tribunais STJ,TRF1
    python -m juris_oficial "BPC e miserabilidade" --tribunais JEF --maximo 3 --ordem data
    python -m juris_oficial "medicamento" --tribunais TRF6 --classe "Agravo de Instrumento" --orgao "3ª Turma"
    python -m juris_oficial --precedentes "acordo de não persecução penal"
    python -m juris_oficial --fontes
    python -m juris_oficial.diagnostico
"""
import argparse
import json
import sys

from . import bnp, fontes
from .comum import markdown


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="juris_oficial", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("busca", nargs="?", default="")
    ap.add_argument("--tribunais", default="STF,STJ,TNU,TRF1")
    ap.add_argument("--maximo", type=int, default=5)
    ap.add_argument("--tipo", choices=["acordao", "monocratica"], default="acordao")
    ap.add_argument("--ordem", choices=["relevancia", "data"], default="relevancia")
    ap.add_argument("--classe", default="", help='só eproc (TNU, TRF2, TRF4, TRF6, TRs, TRUs), ex.: "Agravo de Instrumento"')
    ap.add_argument("--relator", default="", help="só eproc: nome do relator, como a base o escreve")
    ap.add_argument("--orgao", default="", help='só eproc (não na TNU), ex.: "3ª Turma"')
    ap.add_argument("--completo", action="store_true", help="ementa sem corte")
    ap.add_argument("--json", metavar="ARQ", help="grava o resultado completo em JSON")
    ap.add_argument("--precedentes", metavar="BUSCA", help="precedentes qualificados no BNP")
    ap.add_argument("--fontes", action="store_true", help="mostra o mapa de cobertura")
    a = ap.parse_args()
    if a.fontes:
        for c, (d, _) in fontes.FONTES.items():
            print("%-5s %s" % (c, d))
        return 0
    if a.precedentes:
        print(markdown(bnp.buscar(a.precedentes), completo=True))
        return 0
    if not a.busca:
        ap.print_help()
        return 1
    res = fontes.pesquisar(a.busca, a.tribunais, a.maximo, a.tipo, a.ordem,
                           classe=a.classe, relator=a.relator, orgao=a.orgao)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([r.dict() for r in res], f, ensure_ascii=False, indent=2)
    for r in res:
        print(markdown(r, a.completo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
