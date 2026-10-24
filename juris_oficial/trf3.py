# -*- coding: utf-8 -*-
"""TRF3 – pesquisa oficial da 3ª Região (web.trf3.jus.br/jurisprudencia).

Uma só aplicação com três bases, fixadas na sessão por um GET:
  0 = acórdãos do TRF3 | 1 = Recursais (Turmas Recursais de SP e MS + TRU3) |
  2 = decisões monocráticas (TRF3 e Recursais).
O sítio fica atrás do Akamai Bot Manager, que derruba a conexão TLS do `requests`;
o `curl_cffi` (impressão digital TLS de Chrome) passa sem navegador nem captcha.
A lista já traz a ementa e o inteiro teor completos.

Sintaxe: aspas, e, ou, não, adjN, proxN, mesmo, com, $ (curinga).
"""
import html as htmlmod
import re
import time

from .comum import Julgado, Resultado, linha, texto, traduzir

BASE = "https://web.trf3.jus.br/jurisprudencia"
FONTE = "TRF3 – pesquisa oficial (web.trf3.jus.br/jurisprudencia)"
# tribunal -> (base, rótulo do órgão, rótulo JEF do órgão)
ALVOS = {"TRF3": (0, "", ""), "TR3": (1, "", ""),
         "TRU3": (1, "Turma Regional de Uniformização", "Turma Regional de Uniformização")}


def _sessao():
    try:
        from curl_cffi import requests as cr
    except ImportError as e:
        raise RuntimeError("o TRF3 exige o pacote curl_cffi (pip install curl_cffi)") from e
    return cr.Session(impersonate="chrome")


def _extrair(h, tribunal):
    tot = re.search(r'class="qtd-total">([\d.]+)', h)
    julgados = []
    for li in re.findall(r'<li class="acordao-retorno">(.*?)</li>', h, re.S):
        bloco = re.search(r'<div class="informacoes-basicas">(.*?)</div>', li, re.S)
        basicas = [linha(b) for b in re.findall(r'<span class="info[^"]*">(.*?)</span>', bloco.group(1) if bloco else "", re.S)]
        em = re.search(r'class="info info-ementa">(.*?)</span>', li, re.S)
        ementa = texto(em.group(1)) if em else ""
        m = re.search(r"\bEmenta:?\s*(?:Ementa:)?\s*", ementa)
        if m and m.start() < 1500:  # a ementa vem precedida do cabeçalho do PJe
            ementa = ementa[m.end():]
        proc = re.search(r'<div class="processo">.*?<span class="info">(.*?)</span>', li, re.S)
        rel = re.search(r'class="info info-relator">(.*?)</span>', li, re.S)
        links = dict(re.findall(r'class="(btn-[\w-]+)"[^>]*?data-link="([^"]*)"', li, re.S))
        numero = linha(proc.group(1)) if proc else ""
        so_digitos = re.sub(r"\D", "", numero)
        orgao = basicas[1] if len(basicas) > 1 else ""
        julgados.append(Julgado(
            tribunal=("TRU3" if "Uniformiza" in orgao else tribunal),
            processo=numero, classe=basicas[0] if basicas else "", orgao=orgao,
            relator=linha(rel.group(1)) if rel else "",
            data_julgamento=next((b.split(":", 1)[1].strip() for b in basicas if b.startswith("Julgamento")), ""),
            data_publicacao=next((b for b in basicas if "DATA:" in b), ""),
            tipo="acórdão", ementa=ementa,
            link=(htmlmod.unescape(links.get("btn-integra-acordao", "")) or
                  ("http://www.trf3.jus.br/trf3r/index.php?id=20&op=resultado&processo=%s" % so_digitos if so_digitos else "")),
            fonte=FONTE))
    return julgados, (int(tot.group(1).replace(".", "")) if tot else 0)


def buscar(tribunal, busca, maximo=10, sintaxe_nativa=False):
    """tribunal: TRF3, TR3 (todas as Turmas Recursais de SP/MS, com a TRU3) ou TRU3."""
    tribunal = tribunal.upper()
    base, rotulo, rotulo_jef = ALVOS[tribunal]
    consulta = (busca if sintaxe_nativa else traduzir(busca, "trf3"))[:255]
    res = Resultado(fonte=FONTE, tribunal=tribunal, busca=consulta)
    try:
        s = _sessao()
        s.get(BASE + "/" if base == 0 else "%s/home/index/%d" % (BASE, base), timeout=60)
        time.sleep(1)
        tam = 50 if maximo > 30 else 30 if maximo > 10 else 10
        dados = {"chkAcordaos": "on", "chkMostrarLista": "on", "opcaoQtdePagina": str(tam),
                 "txtPesquisaLivre": consulta, "magistrado": "0", "classe": "0", "orgao": "0",
                 "hdnOrgao": "(%s).org." % rotulo if rotulo else "",
                 "hdnOrgaoJef": "(%s).org." % rotulo_jef if rotulo_jef else "",
                 "numero": "", "data_inicial": "", "data_final": "", "data_tipo": "0", "ementa": "",
                 "indexacao": "", "hdnMagistrado": "", "hdnClasse": "", "hdnLegislacao": "",
                 "numclasse": "", "legislacao": ""}
        r = s.post(BASE + "/Home/ResultadoTotais", data=dados, timeout=90)
        r.raise_for_status()
        res.julgados, res.total = _extrair(r.text, tribunal)
        pagina = 2
        while len(res.julgados) < maximo and len(res.julgados) < res.total:
            time.sleep(1)
            r = s.get("%s/Home/ListaResumida/2?np=%d" % (BASE, pagina), timeout=90)
            novos, _ = _extrair(r.text, tribunal)
            if not novos:
                break
            res.julgados.extend(novos)
            pagina += 1
        res.julgados = res.julgados[:maximo]
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
