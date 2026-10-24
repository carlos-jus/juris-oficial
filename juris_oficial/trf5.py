# -*- coding: utf-8 -*-
"""TRF5 – pesquisa "Julia" (juliapesquisa.trf5.jus.br), API JSON aberta.

Origens: G2 (TRF5, 2º grau), TR_AL, TR_CE, TR_PB, TR_PE, TR_RN, TR_SE (Turmas
Recursais) e TRU (TRU5). Cobre a era do PJe. Limites medidos em 24/10/2026: o
total para em 10.000 (teto do Elasticsearch), não há data de publicação nem link
do inteiro teor (o texto integral vem no próprio resultado), e a TRU repete
registros (aqui eliminados).

Sintaxe: aspas, e, ou, nao, adj, prox, $ (curinga).
"""
import html as htmlmod
import re
import time

import requests

from .comum import UA, Julgado, Resultado, traduzir

API = "https://juliapesquisa.trf5.jus.br/julia-pesquisa/api/v1/documento:dt/"
FONTE = "TRF5 – Julia (juliapesquisa.trf5.jus.br)"
CONSULTA_PROCESSUAL = "https://www.trf5.jus.br/index.php/consulta-processual-fisico-e-eletronico"
ORIGENS = {"TRF5": ["G2"], "TRU5": ["TRU"],
           "TR5": ["TR_AL", "TR_CE", "TR_PB", "TR_PE", "TR_RN", "TR_SE"]}
TETO = 10000


def _cnj(n):
    n = re.sub(r"\D", "", n or "")
    return "%s-%s.%s.%s.%s.%s" % (n[:7], n[7:9], n[9:13], n[13], n[14:16], n[16:]) if len(n) == 20 else n


def _limpo(t):
    t = htmlmod.unescape(re.sub(r"</?em>", "", t or ""))
    return re.sub(r"[ \t]+", " ", t).strip()


def _ementa(t):
    linhas = [x.strip() for x in _limpo(t).splitlines()]
    for i, x in enumerate(linhas):
        if x.upper() in ("EMENTA", "EMENTA:"):
            seguinte = next((y for y in linhas[i + 1:] if y), "")
            if seguinte.upper().startswith("PODER JUDICI"):
                continue
            corpo = []
            for y in linhas[i + 1:]:
                if y.upper() in ("RELATÓRIO", "VOTO", "VOTO VENCEDOR", "ACÓRDÃO", "VOTO-VISTA"):
                    break
                if y:
                    corpo.append(y)
            return "\n".join(corpo)
    return "\n".join(x for x in linhas if x)


def _turma(t):
    for x in (t or "").splitlines()[:8]:
        x = x.strip()
        if re.search(r"Turma|Pleno|Seção|Plenário", x) and "Tribunal Regional" not in x:
            return x
    return ""


def buscar(tribunal, busca, maximo=10, desde="", ate="", sintaxe_nativa=False):
    """tribunal: TRF5, TR5 (as seis Turmas Recursais) ou TRU5. desde/ate: dd/mm/aaaa."""
    tribunal = tribunal.upper()
    consulta = busca if sintaxe_nativa else traduzir(busca, "julia")
    res = Resultado(fonte=FONTE, tribunal=tribunal, busca=consulta)
    vistos, total = set(), 0
    try:
        for i, origem in enumerate(ORIGENS[tribunal]):
            if i:
                time.sleep(1)
            params = {"draw": 1, "start": 0, "length": min(max(maximo, 10), 100), "pesquisaLivre": consulta,
                      "numeroProcesso": "", "orgaoJulgador": "", "relator": "", "dataIni": desde, "dataFim": ate}
            r = requests.get(API + origem, params=params, timeout=90,
                             headers={"User-Agent": UA, "Accept": "application/json"})
            r.raise_for_status()
            j = r.json()
            total += j.get("recordsTotal") or 0
            for d in j.get("data") or []:
                chave = (d.get("numeroProcesso"), d.get("codigoDocumento"))
                if chave in vistos:
                    continue
                vistos.add(chave)
                t = d.get("texto") or ""
                orgao = d.get("orgaoJulgador") or ""
                turma = _turma(t) if origem == "G2" else ""
                data = (d.get("dataJulgamento") or "")[:10]
                if len(data) == 10 and data[4] == "-":
                    data = "%s/%s/%s" % (data[8:], data[5:7], data[:4])
                rel = d.get("relator") or ""
                if d.get("relatorAcordao") and d["relatorAcordao"] != rel:
                    rel += " (para o acórdão: %s)" % d["relatorAcordao"]
                ementa = _ementa(t)
                res.julgados.append(Julgado(
                    tribunal=tribunal, processo=_cnj(d.get("numeroProcesso")), classe=d.get("classeJudicial") or "",
                    orgao=(turma + " – " + orgao) if turma and turma not in orgao else orgao,
                    relator=rel, data_julgamento=data, tipo=(d.get("tipoDocumento") or "").lower(),
                    ementa=ementa if origem == "G2" or len(ementa) < 6000 else ementa[:6000] + " [...]",
                    link=d.get("url") or CONSULTA_PROCESSUAL, fonte=FONTE + " – " + origem))
        res.total = total
        res.total_e_minimo = total >= TETO
        # com as seis Turmas Recursais, intercala por data (a API já ordena cada origem assim)
        res.julgados.sort(key=lambda j: j.data_julgamento[6:] + j.data_julgamento[3:5] + j.data_julgamento[:2],
                          reverse=True)
        res.julgados = res.julgados[:maximo]
        res.aviso = ("A Julia não informa a data de publicação nem o link do inteiro teor; nas Turmas "
                     "Recursais e na TRU o texto é o inteiro teor (ementa + voto). Total limitado a 10.000.")
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
