# -*- coding: utf-8 -*-
"""Base ANTIGA de jurisprudência do CJF (antiga-jurisprudencia.cjf.jus.br, JSF).

Desde 23/10/2026 o portal novo do CJF (jurisprudencia.cjf.jus.br) barra qualquer
acesso automatizado (anti-robô F5). A base antiga continua no ar, sem anti-robô,
mas PARADA em vários pontos (medido em 24/10/2026). Aqui ela serve só ao que
ainda não tem fonte melhor:

- TRF1 (2º grau): acervo até ~fev/2024 (depois disso, ver `djen`);
- JEF da 1ª Região (Turmas Recursais e TRU1): até ~ago/2026;
- TNU anterior a jul/2017 (o resto está no eproc da TNU).

Sintaxe: E, OU, NAO, ADJn, PROXn, COM, MESMO (maiúsculos), $ (curinga),
campos entre colchetes ([EMEN], [ORGA], [REL]...).
"""
import re

import requests

from .comum import UA, Julgado, Resultado, linha, texto, traduzir

RAIZ = "https://antiga-jurisprudencia.cjf.jus.br"
FONTE = "CJF – base antiga (antiga-jurisprudencia.cjf.jus.br)"
AJAX = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/xml, text/xml, */*; q=0.01"}
TRU1 = "TURMA REGIONAL DE UNIFORMIZAÇÃO"


class _Formulario:
    """Uma sessão JSF: lê o ViewState e o nome (gerado) do grupo de caixas."""

    def __init__(self, caminho, valor_caixa):
        self.url = RAIZ + caminho
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        r = self.s.get(self.url, timeout=40)
        r.raise_for_status()
        m = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("ViewState ausente em %s (layout mudou?)" % caminho)
        self.viewstate = m.group(1)
        # o nome do grupo (formulario:j_idtNN) muda a cada republicação: lê-se da página
        m = (re.search(r'<input[^>]*name="(formulario:[^"]+)"[^>]*value="%s"' % valor_caixa, r.text) or
             re.search(r'<input[^>]*value="%s"[^>]*name="(formulario:[^"]+)"' % valor_caixa, r.text))
        if not m:
            raise RuntimeError("grupo de caixas com o valor %s ausente (layout mudou?)" % valor_caixa)
        self.grupo = m.group(1)

    def pesquisar(self, consulta, marcados, extras=()):
        dados = [("javax.faces.partial.ajax", "true"), ("javax.faces.source", "formulario:actPesquisar"),
                 ("javax.faces.partial.execute", "@all"), ("javax.faces.partial.render", "formulario:resultado"),
                 ("formulario:actPesquisar", "formulario:actPesquisar"), ("formulario", "formulario"),
                 ("formulario:textoLivre", consulta)]
        dados += [(self.grupo, v) for v in marcados] + list(extras)
        dados.append(("javax.faces.ViewState", self.viewstate))
        r = self.s.post(self.url, data=dados, headers=AJAX, timeout=90)
        r.raise_for_status()
        return r.text


def _extrair(pagina, tribunal_padrao):
    m = re.search(r"([\d.]+)\s*Documento\(s\) encontrado", pagina)
    total = int(m.group(1).replace(".", "")) if m else 0
    julgados = []
    for bloco in re.split(r'<div id="item_resultado-', pagina)[1:]:
        campos = {}
        for mr in re.finditer(r'<span class="label_pontilhada">(.*?)</span>\s*</td>\s*</tr>\s*<tr>\s*<td>(.*?)</td>\s*</tr>',
                              bloco, re.S):
            rot = linha(mr.group(1))
            if rot not in campos:
                campos[rot] = mr.group(2)
        num = texto(campos.get("Número", "")).split("\n")[0]
        teor = re.search(r'href="([^"]+)"', campos.get("Inteiro teor", ""))
        relator = linha(campos.get("Relator(a)", ""))
        if campos.get("Relator para Acórdão"):
            relator += " (para o acórdão: %s)" % linha(campos["Relator para Acórdão"])
        origem = linha(campos.get("Origem", "")) or tribunal_padrao
        orgao = linha(campos.get("Órgão julgador", ""))
        trib = tribunal_padrao
        if tribunal_padrao in ("TR1", "TRU1"):
            trib = "TRU1" if TRU1 in orgao.upper() else "TR1"
        julgados.append(Julgado(
            tribunal=trib, processo=num, classe=linha(campos.get("Classe", "")), orgao=orgao,
            relator=relator, data_julgamento=linha(campos.get("Data", "")),
            data_publicacao=linha(campos.get("Data da publicação", "")) or linha(campos.get("Fonte da publicação", "")),
            tipo=linha(campos.get("Tipo", "")), ementa=texto(campos.get("Ementa", "")),
            decisao=texto(campos.get("Decisão", "")), link=teor.group(1).replace("&amp;", "&") if teor else "",
            fonte=FONTE + (" – origem %s" % origem if origem and origem != tribunal_padrao else "")))
    return julgados, total


def buscar(tribunal, busca, maximo=10, sintaxe_nativa=False):
    """tribunal: TRF1 (até ~fev/2024), TR1, TRU1 (JEF da 1ª Região) ou TNU (acervo do CJF)."""
    tribunal = tribunal.upper()
    consulta = busca if sintaxe_nativa else traduzir(busca, "cjf")
    res = Resultado(fonte=FONTE, tribunal=tribunal, busca=consulta)
    try:
        if tribunal == "TNU":
            f = _Formulario("/unificada/index.xhtml", "STF")
            pagina = f.pesquisar(consulta, ["TNU"])
        elif tribunal in ("TRF1", "TR1", "TRU1"):
            if tribunal == "TRU1":
                consulta = "(%s) E (%s)[ORGA]" % (consulta, '"turma regional de uniformização"')
                res.busca = consulta
            f = _Formulario("/trf1/index.xhtml", "JEF1")
            tipos = [("formulario:selectTiposDocumento", t) for t in ("ACORDAO", "SUMULA")]
            pagina = f.pesquisar(consulta, ["TRF1"] if tribunal == "TRF1" else ["JEF1"], tipos)
        else:
            raise ValueError("a base antiga do CJF só é usada para TRF1, TR1, TRU1 e TNU")
        res.julgados, res.total = _extrair(pagina, tribunal)
        res.julgados = res.julgados[:maximo]
        if tribunal == "TRF1":
            res.aviso = ("Base antiga do CJF: o TRF1 para em ~fev/2024. Julgados posteriores (desde mai/2025) "
                         "vêm do DJEN; de mar/2024 a abr/2025 não há fonte automatizável.")
        elif tribunal in ("TR1", "TRU1"):
            res.aviso = "Base antiga do CJF (JEF da 1ª Região): atualizada até ~ago/2026."
        else:
            res.aviso = "Acervo da TNU no CJF (inclui o período anterior a jul/2017, ausente do eproc da TNU)."
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
