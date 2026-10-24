# -*- coding: utf-8 -*-
"""Módulo de jurisprudência do eproc – o mesmo programa em vários tribunais.

Instâncias (todas respondem a `requests` simples, sem navegador):
- TNU   eproctnu-jur.cjf.jus.br      julgados de jul/2017 em diante (o acervo anterior
                                     está na base antiga do CJF – ver `cjf_antigo`)
- TRF4  jurisprudencia.trf4.jus.br   TRF4, TRU4 e Turmas Recursais da 4ª Região
- TRF6  eproc-jur.trf6.jus.br        TRF6, TRU6 e Turmas Recursais de MG
(TRF2 entra aqui se o levantamento confirmar o mesmo módulo.)

Pesquisa: POST em `...acao=jurisprudencia@jurisprudencia/listar_resultados`.
Sintaxe: aspas, e, ou, não, prox, * (curinga).
"""
import re
import time

import requests

from .comum import UA, Julgado, Resultado, linha, texto, traduzir

INSTANCIAS = {
    # chave: (URL base do controlador, {tribunal: código de origem}, rótulo da fonte)
    "tnu": ("https://eproctnu-jur.cjf.jus.br/eproc/externo_controlador.php",
            {"TNU": "1"}, "eproc TNU (eproctnu-jur.cjf.jus.br)"),
    "trf2": ("https://eproc.trf2.jus.br/eproc/externo_controlador.php",
             {"TRF2": "1", "TRU2": "2", "TR2": "3"}, "eproc TRF2 (eproc.trf2.jus.br)"),
    "trf4": ("https://jurisprudencia.trf4.jus.br/eproc2trf4/externo_controlador.php",
             {"TRF4": "1", "TRU4": "2", "TR4": "3"}, "eproc TRF4 (jurisprudencia.trf4.jus.br)"),
    "trf6": ("https://eproc-jur.trf6.jus.br/eproc/externo_controlador.php",
             {"TRF6": "1", "TRU6": "2", "TR6": "3"}, "eproc TRF6 (eproc-jur.trf6.jus.br)"),
}
TIPOS = {"acordao": "1", "monocratica": "2"}

_sessoes = {}


def _sessao(chave):
    s = _sessoes.get(chave)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        s.get(INSTANCIAS[chave][0] + "?acao=jurisprudencia@jurisprudencia/pesquisar", timeout=40)
        _sessoes[chave] = s
    return s


def _div(html, inicio):
    """Conteúdo do <div ...> que começa em `inicio`, contando divs aninhados."""
    abre = html.find(">", inicio) + 1
    nivel, pos = 1, abre
    for m in re.finditer(r"<div\b|</div>", html[abre:]):
        nivel += 1 if m.group(0) == "<div" else -1
        if nivel == 0:
            return html[abre:abre + m.start()]
        pos = abre + m.end()
    return html[abre:pos]


def _campos(card):
    campos = {}
    for m in re.finditer(r'<div class="resLabel">(.*?)</div>', card, re.S):
        rotulo = linha(m.group(1)).upper()
        v = re.compile(r'<div class="resValue(?! ?TipoJurisprudencia)[^"]*"').search(card, m.end())
        if not v or rotulo in campos:
            continue
        campos[rotulo] = texto(_div(card, v.start()))
    return campos


def _extrair(pagina, tribunal, base, fonte):
    julgados = []
    cards = re.split(r'<div class="card mb-3 resultadoItem"', pagina)[1:]
    for card in cards:
        c = _campos(card)
        proc = c.get("PROCESSO", "")
        partes = [p.strip() for p in proc.split("\n") if p.strip()]
        m = re.search(r'class="[^"]*numero-processo[^"]*"[^>]*>(.*?)</a>\s*(?:<span[^>]*>(.*?)</span>)?', card, re.S)
        if m:
            partes = [linha(m.group(1))] + ([linha(m.group(2))] if m.group(2) else [])
        tipo = re.search(r'resValueTipoJurisprudencia">(.*?)</div>', card, re.S)
        teor = re.search(r'class="[^"]*inteiroTeor[^"]*"[^>]*data-link="([^"]+)"', card) or \
            re.search(r'data-link="([^"]*download_inteiro_teor[^"]*)"', card)
        link = ""
        if teor:
            link = base.rsplit("/", 1)[0] + "/" + re.sub(r"&termosPesquisados=[^&]*", "", teor.group(1).replace("&amp;", "&"))
        cit = re.search(r'data-citacao="(.*?)"', card, re.S)
        citacao = linha(cit.group(1)) if cit else ""
        mref = re.search(r"\(([A-Z]{2,4}\d?,[^()]*(?:\([^()]*\)[^()]*)*)\)\s*$", citacao)
        # a citação pronta ("(TRF4, Rcl 50256..., 3ª Seção, Relator X, julgado em ...)") supre
        # a classe (TRF4/TRF6 não a põem no card) e o órgão (a TNU não o põe).
        ref = [p.strip() for p in mref.group(1).split(",")] if mref else []
        if ref and len(partes) < 2 and len(ref) > 1 and " " in ref[1]:
            partes = (partes or [ref[1].split(" ", 1)[1]]) + [ref[1].split(" ", 1)[0]]
        if ref and not c.get("ÓRGÃO JULGADOR") and len(ref) > 2:
            c["ÓRGÃO JULGADOR"] = re.sub(r"\b(De|Da|Do|Das|Dos|E)\b", lambda x: x.group(1).lower(),
                                         ref[2].title()) if ref[2].isupper() else ref[2]
        relator = c.get("RELATOR") or c.get("RELATORA") or c.get("RELATOR(A)") or ""
        if c.get("RELATOR PARA ACÓRDÃO"):
            relator += " (para o acórdão: %s)" % c["RELATOR PARA ACÓRDÃO"]
        julgados.append(Julgado(
            tribunal=tribunal,
            processo=partes[0] if partes else "",
            classe=re.sub(r"\s+", " ", partes[1]) if len(partes) > 1 else "",
            orgao=c.get("ÓRGÃO JULGADOR", ""),
            relator=relator.strip(),
            data_julgamento=c.get("DATA DO JULGAMENTO", "") or c.get("DATA DA DECISÃO", ""),
            data_publicacao=c.get("DATA DA PUBLICAÇÃO", ""),
            tipo=linha(tipo.group(1)) if tipo else "",
            ementa=c.get("EMENTA", ""),
            decisao=c.get("DECISÃO", ""),
            link=link,
            citacao=("(" + mref.group(1) + ")") if mref else "",
            fonte=fonte,
        ))
    return julgados


def buscar(tribunal, busca, maximo=10, tipo="acordao", ordem="relevancia", campo="inteiro_teor",
           desde="", ate="", sintaxe_nativa=False):
    """tribunal: TNU, TRF4, TRU4, TR4, TRF6, TRU6, TR6. desde/ate: dd/mm/aaaa (julgamento)."""
    tribunal = tribunal.upper()
    chave = next((k for k, (_, ori, _) in INSTANCIAS.items() if tribunal in ori), None)
    if not chave:
        raise ValueError("tribunal sem base eproc: %s" % tribunal)
    base, origens, fonte = INSTANCIAS[chave]
    consulta = busca if sintaxe_nativa else traduzir(busca, "eproc")
    res = Resultado(fonte=fonte, tribunal=tribunal, busca=consulta)
    tam = 100 if maximo > 50 else 50 if maximo > 25 else 25 if maximo > 10 else 10
    dados = {"txtPesquisa": consulta, "selOrigem[]": origens[tribunal],
             "selTipoDocumento[]": TIPOS.get(tipo, "1"), "rdoCampo": "E" if campo == "ementa" else "I",
             "chkAgruparResultados": "on", "selTamanhoPagina": str(tam),
             "dtDecisaoInicio": desde, "dtDecisaoFim": ate}
    if ordem == "data":
        dados["selOrdenacao"] = "1"
    try:
        s = _sessao(chave)
        pagina_n = 1
        while len(res.julgados) < maximo:
            dados["hdnPaginaAtual"] = str(pagina_n)
            r = s.post(base + "?acao=jurisprudencia@jurisprudencia/listar_resultados", data=dados, timeout=90)
            r.encoding = "iso-8859-1"
            if "/indisp/" in r.url or "Indisponibilidade" in r.text[:600]:
                _sessoes.pop(chave, None)
                raise RuntimeError("o eproc do tribunal está em manutenção (página de indisponibilidade: "
                                   "\"sistema em atualização\"); tente de novo mais tarde")
            m = re.search(r'id="hdnTotalResultado"[^>]*value="(\d+)"', r.text)
            res.total = int(m.group(1)) if m else (0 if re.search(r"Nenhum|0 documentos", r.text) else None)
            novos = _extrair(r.text, tribunal, base, fonte)
            if not novos:
                break
            res.julgados.extend(novos)
            tp = re.search(r'id="hdnTotalPaginas"[^>]*value="(\d+)"', r.text)
            if not tp or pagina_n >= int(tp.group(1)):
                break
            pagina_n += 1
            time.sleep(1)
        res.julgados = res.julgados[:maximo]
        if res.total is None:
            res.erro = "a base respondeu sem o total de resultados (layout mudou?)"
    except Exception as e:  # noqa: BLE001
        _sessoes.pop(chave, None)
        res.erro = "%s: %s" % (type(e).__name__, e)
    if tribunal == "TNU" and not res.erro:
        res.aviso = ("Esta base tem os julgados da TNU de jul/2017 em diante; o acervo anterior "
                     "fica na base antiga do CJF (buscar_tnu já consulta as duas quando pedido).")
    return res
