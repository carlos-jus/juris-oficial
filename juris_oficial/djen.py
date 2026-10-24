# -*- coding: utf-8 -*-
"""TRF1 recente – acórdãos publicados no DJEN (Diário de Justiça Eletrônico Nacional).

A base de jurisprudência do TRF1 é servida pelo CJF, cujo portal novo barra acesso
automatizado e cuja base antiga para em ~fev/2024. Desde mai/2025 o TRF1 publica
no DJEN cada acórdão do 2º grau como "Intimação automática – inteiro teor do
acórdão", com relatório, voto, ementa e acórdão no campo `texto`. A API do DJEN
(comunicaapi.pje.jus.br, CNJ) é pública e sem anti-robô.

Limites (medidos em 24/10/2026), que a ferramenta informa no resultado:
- a API busca uma FRASE EXATA (sem e/ou): a frase mais longa da busca vai à API e os
  demais termos são conferidos aqui, sem acento e sem caixa;
- a mesma decisão sai uma vez por destinatário (aqui se eliminam as repetições);
- quase nunca há a data da sessão – vale a data de publicação;
- 20 requisições por janela; total limitado a 10.000;
- de mar/2024 a abr/2025 não há acórdãos sistemáticos (nem aqui nem na base antiga).
"""
import datetime as dt
import re
import time
import unicodedata

import requests

from .comum import UA, Julgado, Resultado

API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
FONTE = "TRF1 – acórdãos no DJEN (comunicaapi.pje.jus.br)"
RX_EMENTA = re.compile(r"\bE\s?M\s?E\s?N\s?T\s?A\b")
RX_ACORDAO = re.compile(r"\bA\s?C\s?Ó\s?R\s?D\s?Ã\s?O\b")
RX_ASSINATURA = re.compile(r"\s+(?:Desembargador|Desembargadora|Juiz|Juíza)(?: Federal)?(?: Convocad[oa])? "
                           r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]+ Relator[a]?\s*$")


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def _termos(busca):
    """Separa a busca simples em frases/palavras obrigatórias e excluídas."""
    obrig, excl, negar = [], [], False
    for tok in re.findall(r'"[^"]*"|\S+', busca or ""):
        k = _sem_acento(tok.strip('"'))
        if k in ("e", "and", "ou", "or"):
            continue
        if k in ("nao", "not"):
            negar = True
            continue
        (excl if negar else obrig).append(tok.strip('"').rstrip("$*"))
        negar = False
    return obrig, excl


def _campo(rx, t):
    m = re.search(rx, t)
    return m.group(1).strip() if m else ""


def _acordao(it):
    t = it.get("texto") or ""
    cab = t[:400]
    if "inteiro teor do acórdão" not in cab or "Tribunal Regional Federal da 1ª Região" not in cab \
            or "Turma Recursal" in (it.get("nomeOrgao") or ""):
        return None
    fim = t.find("OBSERVAÇÃO 1")
    fim = fim if fim > 0 else len(t)
    acs = list(RX_ACORDAO.finditer(t, 0, fim))
    i_ac = acs[-1].start() if acs else fim
    ems = list(RX_EMENTA.finditer(t, 0, i_ac))
    ementa = RX_ASSINATURA.sub("", t[ems[-1].end():i_ac].strip()) if ems else ""
    dispositivo = t[acs[-1].end():fim].strip() if acs else ""
    relator = re.split(r"\s+(?:PODER|JUSTIÇA|RELATÓRIO|VOTO|EMENTA)\b",
                       _campo(r"RELATOR\(A\):\s*(.{0,120})", t))[0]
    pub = it.get("data_disponibilizacao") or ""
    if len(pub) == 10 and pub[4] == "-":
        pub = "%s/%s/%s (DJEN)" % (pub[8:], pub[5:7], pub[:4])
    return Julgado(
        tribunal="TRF1", processo=it.get("numeroprocessocommascara") or it.get("numero_processo") or "",
        classe=it.get("nomeClasse") or "",
        orgao=_campo(r"Tribunal Regional Federal da 1ª Região\s+(.+?)\s+Intimação automática", cab),
        relator=relator, data_julgamento="", data_publicacao=pub, tipo="acórdão",
        ementa=ementa, decisao=dispositivo[:1500], link=it.get("link") or "",
        fonte=FONTE), _campo(r"acórdão proferido \(ID (\d+)\)", t)


def buscar(busca, maximo=10, dias=365, paginas=3):
    obrig, excl = _termos(busca)
    if not obrig:
        return Resultado(fonte=FONTE, tribunal="TRF1", busca=busca, erro="busca vazia")
    frase = max(obrig, key=len)
    res = Resultado(fonte=FONTE, tribunal="TRF1", busca="%s  [frase enviada ao DJEN: \"%s\"]" % (busca, frase))
    fim = dt.date.today()
    ini = fim - dt.timedelta(days=dias)
    vistos, varridos = set(), 0
    try:
        for pagina in range(1, paginas + 1):
            r = requests.get(API, timeout=60, headers={"User-Agent": UA, "Accept": "application/json"},
                             params={"siglaTribunal": "TRF1", "texto": frase,
                                     "dataDisponibilizacaoInicio": ini.isoformat(),
                                     "dataDisponibilizacaoFim": fim.isoformat(),
                                     "itensPorPagina": 100, "pagina": pagina})
            if r.status_code == 429:
                res.aviso = "a API do DJEN limitou as requisições (20 por janela); tente de novo em instantes. "
                break
            r.raise_for_status()
            j = r.json()
            if pagina == 1:
                res.total = j.get("count")
                res.total_e_minimo = (res.total or 0) >= 10000
            itens = j.get("items") or []
            varridos += len(itens)
            for it in itens:
                achado = _acordao(it)
                if not achado:
                    continue
                julgado, id_acordao = achado
                chave = (julgado.processo, id_acordao or julgado.ementa[:80])
                if chave in vistos:
                    continue
                corpo = _sem_acento(it.get("texto"))
                if any(_sem_acento(o) not in corpo for o in obrig) or any(_sem_acento(x) in corpo for x in excl):
                    continue
                vistos.add(chave)
                res.julgados.append(julgado)
            if len(res.julgados) >= maximo or len(itens) < 100:
                break
            time.sleep(1.2)
        res.julgados = res.julgados[:maximo]
        res.aviso += ("DJEN (TRF1, 2º grau, desde mai/2025): o total acima conta TODAS as comunicações do TRF1 "
                      "com a frase (1º e 2º graus, repetidas por destinatário); foram examinadas %d, das quais "
                      "%d acórdãos distintos do 2º grau. A data é a de publicação; a da sessão raramente consta."
                      % (varridos, len(res.julgados)))
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
