# -*- coding: utf-8 -*-
"""STJ – busca livre no SCON (scon.stj.jus.br), acervo inteiro: acórdãos e decisões
monocráticas.

O SCON fica atrás do Cloudflare: só responde ao `fetch` feito de dentro de uma aba
do navegador próprio (ver `navegador`). A página de resultado vem montada no
servidor; cada documento traz a ementa em texto puro (o `textarea` do botão
"copiar ementa") e o link ESTÁVEL do inteiro teor.

Sintaxe do SCON: e, ou, nao, adj, prox, aspas, $ (curinga).
"""
import html as htmlmod
import re
import threading
import time
import urllib.parse

from . import navegador
from .comum import Julgado, Resultado, texto, traduzir

BASE = "https://scon.stj.jus.br"
BASES = {"acordao": "ACOR", "monocratica": "DTXT"}
ORDENS = {"relevancia": "TEMA,-DTPB,-@DOCN,@NUM,CLAS", "data": "-DTPB,@NUM,CLAS"}
FONTE = "SCON/STJ (scon.stj.jus.br)"
CAMPOS = {"Processo": "processo", "Relator": "relator", "Relatora": "relator", "Relator(a)": "relator",
          "Órgão Julgador": "orgao", "Data do Julgamento": "data_julgamento",
          "Data da Publicação/Fonte": "data_publicacao", "Data da Publicação": "data_publicacao",
          "Tese Jurídica": "tese", "Ementa": "ementa_html", "Acórdão": "decisao", "Decisão": "decisao"}

_aba = None
_trava = threading.Lock()  # uma aba por base: buscas simultâneas fazem fila


def _pronto(titulo):
    return "momento" not in (titulo or "").lower()


def _abrir():
    global _aba
    if _aba is None:
        _aba = navegador.Aba()
        _aba.ir(BASE + "/SCON/", pronto_quando=_pronto, espera=60)
    return _aba


def _descartar():
    global _aba
    if _aba is not None:
        _aba.fechar()
    _aba = None


def _pagina(caminho):
    for tentativa in (1, 2):
        try:
            st, tx = _abrir().buscar(caminho, codificacao="iso-8859-1")
            if st == 200 and "Um momento" not in tx[:3000]:
                return tx
            raise RuntimeError("SCON devolveu %s" % st)
        except Exception:
            _descartar()
            if tentativa == 2:
                raise


def _url(consulta, base, ordem, inicio):
    q = urllib.parse.urlencode({
        "acao": "pesquisar", "novaConsulta": "true", "livre": consulta, "b": base, "p": "false",
        "l": "10", "i": str(inicio), "ordenacao": ordem, "tp": "T", "h": "true"}, encoding="iso-8859-1")
    return "/SCON/pesquisar.jsp?" + q


def _extrair(pagina, base):
    m = re.search(r"Documento \d+ de ([\d.]+)", pagina)
    total = int(m.group(1).replace(".", "")) if m else 0
    docs = []
    for bloco in pagina.split('<div class="documento">')[1:]:
        bloco = re.split(r'<a name="DOC\d+"', bloco)[0]
        d = {}
        # cada campo é um `paragrafoBRS`; o rótulo pode ter um `div.hint` aninhado
        for par in bloco.split('<div class="paragrafoBRS">')[1:]:
            mr = re.search(r'<div class="docTitulo[^"]*"[^>]*>(.*?)(?:<i |<div|</div>)', par, re.S)
            mt = re.search(r'<div class="docTexto[^"]*"[^>]*>(.*)', par, re.S)
            if mr and mt:
                rot = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", mr.group(1)))).strip()
                chave = CAMPOS.get(rot)
                if chave and chave not in d:
                    d[chave] = texto(mt.group(1))
        if d.get("tese"):  # o SCON fecha a tese com o link "Veja o Tema Repetitivo N"
            d["tese"] = re.sub(r"\s*Veja o Tema Repetitivo \d+\s*$", "", d["tese"])
        bruto = d.get("processo", "")
        linhas = bruto.split("\n")
        tema = re.search(r"Tema(?: Repetitivo)?\s+(\d+)", bruto)
        mt = re.search(r'<textarea[^>]*textareaSemformatacao[^>]*>(.*?)</textarea>', bloco, re.S)
        ementa = htmlmod.unescape(mt.group(1)).strip() if mt else d.get("ementa_html", "")
        link = ""
        mi = re.search(r"GetInteiroTeorDoAcordao\?num_registro=(\d+)&(?:amp;)?dt_publicacao=([\d/]+)", bloco)
        if mi:
            link = "%s/SCON/GetInteiroTeorDoAcordao?num_registro=%s&dt_publicacao=%s" % (BASE, mi.group(1), mi.group(2))
        mm = re.search(r"processo\.stj\.jus\.br/processo/monocraticas/decisoes/\?num_registro=(\d+)&(?:amp;)?dt_publicacao=([\d/]+)", bloco)
        if mm and not link:
            link = ("https://processo.stj.jus.br/processo/monocraticas/decisoes/?num_registro=%s&dt_publicacao=%s"
                    % (mm.group(1), mm.group(2)))
        ident = linhas[0] if linhas else ""
        cl = re.match(r"(.+?)\s+(\d[\d.]*)\s*(?:/\s*([A-Z]{2}))?$", ident)
        docs.append(Julgado(
            tribunal="STJ",
            classe=cl.group(1) if cl else "",
            processo=("%s/%s" % (cl.group(2), cl.group(3)) if cl and cl.group(3) else cl.group(2) if cl else ident),
            orgao=d.get("orgao", ""), relator=d.get("relator", ""),
            data_julgamento=d.get("data_julgamento", ""), data_publicacao=d.get("data_publicacao", ""),
            tipo=("acórdão" if base == "ACOR" else "decisão monocrática"),
            ementa=ementa if base == "ACOR" else "", decisao=(d.get("decisao", "") if base == "ACOR" else ementa),
            tese=(("Tema %s – " % tema.group(1)) if tema and d.get("tese") else "") + d.get("tese", ""),
            link=link, fonte=FONTE))
    return docs, total


def buscar(busca, *args, **kwargs):
    with _trava:
        return _buscar(busca, *args, **kwargs)


def _buscar(busca, maximo=10, tipo="acordao", ordem="relevancia", sintaxe_nativa=False):
    consulta = busca if sintaxe_nativa else traduzir(busca, "scon")
    res = Resultado(fonte=FONTE, tribunal="STJ", busca=consulta)
    base = BASES.get(tipo, "ACOR")
    try:
        inicio = 1
        while len(res.julgados) < maximo:
            novos, res.total = _extrair(_pagina(_url(consulta, base, ORDENS.get(ordem, ORDENS["relevancia"]), inicio)), base)
            if not novos:
                break
            res.julgados.extend(novos)
            inicio += 10
            if inicio > res.total:
                break
            time.sleep(1.5)  # o SCON mostra captcha quando há excesso
        res.julgados = res.julgados[:maximo]
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
