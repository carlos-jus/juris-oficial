# -*- coding: utf-8 -*-
"""STF – base oficial de jurisprudência (jurisprudencia.stf.jus.br): acórdãos,
decisões monocráticas e súmulas.

O portal fica atrás do WAF da AWS: a API (`/api/search/search`, Elasticsearch)
só responde ao `fetch` feito de dentro de uma aba aberta no portal.

Sintaxe: termos com AND implícito, "expressão exata", OR, NOT, * (curinga).
Prefixo `proc:` busca um processo exato (ex.: `proc:HC 185913`).
"""
import json
import threading
import time

from . import navegador
from .comum import Julgado, Resultado, linha, texto, traduzir

PORTAL = "https://jurisprudencia.stf.jus.br"
FONTE = "STF – base oficial (jurisprudencia.stf.jus.br)"
BASES = {"acordao": "acordaos", "monocratica": "decisoes", "sumula": "sumulas"}
CAMPOS = ["processo_codigo_completo.plural", "acordao_ata.plural^3", "documental_indexacao_texto.plural",
          "documental_legislacao_citada_texto.plural", "documental_tese_texto.plural^3",
          "ementa_texto.plural^3", "ministro_facet.plural", "orgao_julgador.plural", "titulo.plural^6",
          "decisao_texto.plural^2", "sumula_texto.plural^3"]

_aba = None
_trava = threading.Lock()  # uma aba por base: buscas simultâneas fazem fila


def _abrir():
    global _aba
    if _aba is None or not _aba.valida():
        _aba = navegador.Aba()
        _aba.ir(PORTAL + "/pages/search", espera=60)
        time.sleep(6)  # o desafio do WAF grava o cookie depois do carregamento
    return _aba


def _descartar():
    global _aba
    if _aba is not None:
        _aba.fechar()
    _aba = None


def _consulta(q, base, tamanho, inicio, ordem):
    filtro_base = {"post_filter": {"bool": {"must": [{"term": {"base": base}}]}}}
    if q.startswith("proc:"):
        classe, numero = q[5:].strip().split(" ", 1)
        query = {"bool": {"filter": [
            {"term": {"processo_classe_processual_unificada_sigla.keyword": classe}},
            {"term": {"processo_numero": int(numero.replace(".", ""))}}]}}
        sort = [{"julgamento_data": "desc"}]
    else:
        query = {"bool": {"filter": [{"query_string": {
            "default_operator": "AND", "fields": CAMPOS, "query": q, "type": "cross_fields",
            "analyzer": "legal_search_analyzer", "quote_analyzer": "legal_index_analyzer"}}]}}
        sort = [{"julgamento_data": "desc"}] if ordem == "data" else [{"_score": "desc"}]
    return dict(query=query, _source=True, size=tamanho, **{"from": inicio}, sort=sort,
                track_total_hits=True, **filtro_base)


def _julgado(src, base):
    def g(k):
        v = src.get(k)
        return ", ".join(map(str, v)) if isinstance(v, list) else (str(v) if v is not None else "")
    data = g("julgamento_data")[:10]
    if len(data) == 10 and data[4] == "-":
        data = "%s/%s/%s" % (data[8:10], data[5:7], data[:4])
    pub = g("publicacao_data")[:10]
    if len(pub) == 10 and pub[4] == "-":
        pub = "%s/%s/%s" % (pub[8:10], pub[5:7], pub[:4])
    titulo = g("titulo")
    return Julgado(
        tribunal="STF", processo=titulo or g("processo_codigo_completo"),
        classe="", orgao=g("orgao_julgador"),
        relator=g("relator_acordao_nome") or g("relator_processo_nome") or g("ministro_facet"),
        data_julgamento=data, data_publicacao=(pub + " " + linha(g("documental_publicacao_lista_texto"))).strip(),
        tipo={"acordaos": "acórdão", "decisoes": "decisão monocrática", "sumulas": "súmula"}[base],
        ementa=texto(g("ementa_texto")) or texto(g("sumula_texto")),
        decisao=texto(g("acordao_ata")) or texto(g("decisao_texto")),
        tese=texto(g("documental_tese_texto")),
        link=g("inteiro_teor_url") or g("acompanhamento_processual_url"),
        fonte=FONTE)


def buscar(busca, *args, **kwargs):
    with _trava, navegador.em_uso():
        return _buscar(busca, *args, **kwargs)


def _buscar(busca, maximo=10, tipo="acordao", ordem="relevancia", sintaxe_nativa=False):
    consulta = busca if (sintaxe_nativa or busca.startswith("proc:")) else traduzir(busca, "stf")
    base = BASES.get(tipo, "acordaos")
    res = Resultado(fonte=FONTE, tribunal="STF", busca=consulta)
    for tentativa in (1, 2):
        try:
            corpo = json.dumps(_consulta(consulta, base, min(maximo, 100), 0, ordem), ensure_ascii=False)
            st, tx = _abrir().buscar(PORTAL + "/api/search/search", "POST", corpo,
                                     {"Content-Type": "application/json", "Accept": "application/json"})
            if st != 200:
                raise RuntimeError("API do STF devolveu %s" % st)
            dados = json.loads(tx).get("result", {}).get("hits", {})
            res.total = (dados.get("total") or {}).get("value")
            res.julgados = [_julgado(h.get("_source", {}), base) for h in dados.get("hits", [])][:maximo]
            res.erro = ""
            break
        except Exception as e:  # noqa: BLE001
            _descartar()
            res.erro = "%s: %s" % (type(e).__name__, e)
    return res
