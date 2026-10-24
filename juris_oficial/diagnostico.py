# -*- coding: utf-8 -*-
"""Teste real de cada fonte: responde? quantos resultados? qual o julgado mais recente?

    python -m juris_oficial.diagnostico            (todas as fontes)
    python -m juris_oficial.diagnostico STJ,TRF1   (só algumas)
"""
import datetime as dt
import re
import sys
import time

from . import bnp, fontes

BUSCA = "benefício"           # termo comum a todas as bases
DEFASAGEM_ACEITA = 120        # dias; mais que isso = base parada


def _data(j):
    for campo in (j.data_julgamento, j.data_publicacao):
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", campo or "")
        if m:
            try:
                return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
    return None


def verificar(codigo):
    t0 = time.time()
    # a base antiga do CJF (TR1/TRU1) não ordena por data: amostra maior para achar o mais recente
    sem_ordem = codigo in ("TR1", "TRU1")
    r = fontes.pesquisar(BUSCA, codigo, maximo=30 if sem_ordem else 10, ordem="data")[0]
    if sem_ordem and not r.erro:
        r.fonte += " (sem ordenação por data: 'mais recente' é o maior de 30 por relevância)"
    seg = time.time() - t0
    datas = [d for d in (_data(j) for j in r.julgados) if d]
    recente = max(datas) if datas else None
    if r.erro:
        situacao = "FALHOU"
    elif not r.julgados:
        situacao = "SEM RESULTADO"
    elif recente and (dt.date.today() - recente).days > DEFASAGEM_ACEITA:
        situacao = "VERIFICAR" if sem_ordem else "DESATUALIZADA"
    else:
        situacao = "OK"
    return {"codigo": codigo, "situacao": situacao, "total": r.total, "minimo": r.total_e_minimo,
            "recente": recente.strftime("%d/%m/%Y") if recente else "-", "segundos": seg,
            "erro": r.erro, "fonte": r.fonte}


def relatorio(tribunais="TODOS"):
    alvos = list(fontes.FONTES) if (tribunais or "TODOS").upper() == "TODOS" else fontes.codigos(tribunais)
    linhas = ["| Código | Situação | Total (\"%s\") | Mais recente | Tempo | Observação |" % BUSCA,
              "|---|---|---|---|---|---|"]
    for c in alvos:
        v = verificar(c)
        tot = ("≥" if v["minimo"] else "") + ("{:,}".format(v["total"]).replace(",", ".") if v["total"] is not None else "?")
        linhas.append("| %s | %s | %s | %s | %.1f s | %s |" % (c, v["situacao"], tot, v["recente"], v["segundos"],
                                                             (v["erro"] or v["fonte"])[:90]))
    b = bnp.buscar("benefício", maximo=1)
    linhas.append("| BNP | %s | %s | – | – | %s |" % ("FALHOU" if b.erro else "OK", b.total, (b.erro or b.fonte)[:90]))
    return "\n".join(linhas)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(relatorio(sys.argv[1] if len(sys.argv) > 1 else "TODOS"))
