# -*- coding: utf-8 -*-
"""Precedentes qualificados – Banco Nacional de Precedentes (BNP/Pangea, CNJ).

API pública (pangeabnp.pdpj.jus.br), sem login: repercussão geral, repetitivos,
súmulas, súmulas vinculantes, IRDR, IAC e PUIL de todos os tribunais.
Traz a questão, a tese e a situação do tema – não traz julgados comuns.
"""
import requests

from .comum import UA, Julgado, Resultado, texto

API = "https://pangeabnp.pdpj.jus.br/api/v1/precedentes"
FONTE = "BNP/Pangea – CNJ (pangeabnp.pdpj.jus.br)"
TIPOS = {"RG": "Repercussão Geral", "RR": "Recurso Repetitivo", "SV": "Súmula Vinculante", "SUM": "Súmula",
         "IRDR": "IRDR", "IAC": "IAC", "PUIL": "PUIL", "CT": "Controvérsia", "TR": "Tema de TRU/TR"}


def buscar(busca="", orgaos="STF,STJ", tipos="RG,RR,SV,SUM", maximo=10, numero=""):
    """`numero` busca o tema/súmula pelo número (ex.: numero="1098", tipos="RR")."""
    filtro = {"buscaGeral": busca, "todasPalavras": "", "quaisquerPalavras": "", "semPalavras": "",
              "trechoExato": "", "atualizacaoDesde": "", "atualizacaoAte": "", "cancelados": False,
              "ordenacao": "Text", "nr": str(numero or ""), "pagina": 1, "tamanhoPagina": min(maximo, 50),
              "orgaos": [o.strip().upper() for o in orgaos.split(",") if o.strip()],
              "tipos": [t.strip().upper() for t in tipos.split(",") if t.strip()]}
    res = Resultado(fonte=FONTE, tribunal=orgaos.upper(), busca=busca or ("nº " + str(numero)))
    try:
        r = requests.post(API, json={"filtro": filtro}, timeout=40,
                          headers={"Accept": "application/json", "User-Agent": UA})
        r.raise_for_status()
        d = r.json()
        res.total = d.get("total")
        for it in d.get("resultados") or []:
            paradigma = (it.get("processosParadigma") or [{}])[0]
            hist = it.get("historico") or []
            res.julgados.append(Julgado(
                tribunal=it.get("orgao", ""), processo="%s %s" % (TIPOS.get(it.get("tipo"), it.get("tipo")), it.get("nr")),
                tipo=TIPOS.get(it.get("tipo"), it.get("tipo") or ""),
                orgao="situação: %s" % (it.get("situacao") or "?"),
                data_publicacao="atualizado em %s" % it.get("ultimaAtualizacao", "?"),
                ementa=texto(it.get("questao") or ""), tese=texto(it.get("tese") or ""),
                decisao=("histórico: " + "; ".join("%s %s" % ((h.get("dataCriacao") or "")[:10], h.get("situacao"))
                                                   for h in hist[-3:])) if hist else "",
                link=paradigma.get("link") or "", fonte=FONTE))
        res.aviso = "No BNP, \"Ementa\" é a QUESTÃO submetida a julgamento; a tese vem em campo próprio."
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
