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
- a busca geral é soterrada pelas publicações de 1º grau; por isso, no TRF1, a frase é
  buscada em cada gabinete do 2º grau (lista descoberta e guardada por 30 dias), com os
  acórdãos que trazem os termos na EMENTA primeiro;
- 20 requisições por janela; total limitado a 10.000;
- de mar/2024 a abr/2025 não há acórdãos sistemáticos (nem aqui nem na base antiga).
"""
import datetime as dt
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests

from .comum import UA, Julgado, Resultado

API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
FONTE = "TRF1 – acórdãos no DJEN (comunicaapi.pje.jus.br)"
# "EMENTA", "E M E N T A" ou "Ementa:" (caixa mista com dois-pontos, comum nos acórdãos do PJe)
RX_EMENTA = re.compile(r"\bE\s?M\s?E\s?N\s?T\s?A\b|\bEmenta\s*:")
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


def _instancia(it):
    """TRF1 (2º grau), TRU1 ou TR1 – pelo órgão que publicou e pelo cabeçalho do texto."""
    t = it.get("texto") or ""
    nome, cab = it.get("nomeOrgao") or "", t[:400]
    if " na TRU" in nome or "Turma Regional de Uniformização" in cab[:250]:
        return "TRU1"
    if "Turma Recursal" in nome or "Turma Recursal" in cab[:250]:
        return "TR1"
    if "inteiro teor do acórdão" in cab and "Tribunal Regional Federal da 1ª Região" in cab:
        return "TRF1"
    return None


def _acordao(it, instancia="TRF1"):
    t = it.get("texto") or ""
    cab = t[:400]
    if _instancia(it) != instancia:
        return None
    # nas Turmas Recursais e na TRU só interessa o acórdão (pauta e intimação não têm ementa)
    if instancia != "TRF1" and not (RX_EMENTA.search(t) and (RX_ACORDAO.search(t) or "acordam" in t.lower())):
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
    if not relator:  # sem "RELATOR(A):" no texto: o gabinete que publicou identifica o relator
        m = re.match(r"Gab\.\s*\d+\s*-\s*(.+)", it.get("nomeOrgao") or "")
        relator = ("%s (gabinete que publicou)" % m.group(1).strip()) if m else ""
    pub = it.get("data_disponibilizacao") or ""
    if len(pub) == 10 and pub[4] == "-":
        pub = "%s/%s/%s (DJEN)" % (pub[8:], pub[5:7], pub[:4])
    orgao = (_campo(r"Tribunal Regional Federal da 1ª Região\s+(.+?)\s+Intimação automática", cab)
             if instancia == "TRF1" else (it.get("nomeOrgao") or ""))
    return Julgado(
        tribunal=instancia, processo=it.get("numeroprocessocommascara") or it.get("numero_processo") or "",
        classe=it.get("nomeClasse") or "",
        orgao=orgao,
        relator=relator, data_julgamento="", data_publicacao=pub, tipo="acórdão",
        ementa=ementa, decisao=dispositivo[:1500], link=it.get("link") or "",
        fonte=FONTE), _campo(r"acórdão proferido \(ID (\d+)\)", t)


CACHE_ORGAOS = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                            "juris-oficial", "orgaos_djen_trf1.json")
_H = {"User-Agent": UA, "Accept": "application/json"}
# frase usada para DESCOBRIR os órgãos de cada instância (o que importa é o órgão que publica)
_DESCOBERTA = {"TRF1": "inteiro teor do acórdão", "TR1": "Turma Recursal",
               "TRU1": "Turma Regional de Uniformização"}


def _get(params, tentativas=3):
    """GET na API respeitando o limite (20 requisições a cada ~7 s)."""
    for i in range(tentativas):
        r = requests.get(API, params=params, headers=_H, timeout=60)
        if r.status_code == 429 and i < tentativas - 1:
            time.sleep(4)
            continue
        r.raise_for_status()
        return r.json()


def orgaos(instancia="TRF1", renovar=False):
    """{idOrgao: nome} dos órgãos da instância (TRF1 = gabinetes do 2º grau; TR1 = relatorias
    das Turmas Recursais; TRU1 = representações na TRU) que publicam no DJEN.

    A API filtra por UM órgão por vez (orgaoId) e não tem filtro de instância, e as
    publicações de 1º grau soterram os acórdãos numa busca geral. Por isso a lista é
    descoberta varrendo 18 janelas mensais (~1 min por instância) e fica em cache por 30 dias."""
    try:
        item = _ler_cache().get(instancia) or {}
        if not renovar and item.get("orgaos") and \
                (dt.date.today() - dt.date.fromisoformat(item["data"])).days <= 30:
            return {int(k): v for k, v in item["orgaos"].items()}
    except Exception:
        pass
    achados, hoje = {}, dt.date.today()
    for m in range(18):
        fim = hoje - dt.timedelta(days=30 * m)
        for p in (1, 2, 3):
            j = _get({"siglaTribunal": "TRF1", "texto": _DESCOBERTA[instancia],
                      "dataDisponibilizacaoInicio": (fim - dt.timedelta(days=6)).isoformat(),
                      "dataDisponibilizacaoFim": fim.isoformat(), "itensPorPagina": 100, "pagina": p})
            for it in j.get("items") or []:
                if _instancia(it) == instancia and it.get("idOrgao"):
                    achados[int(it["idOrgao"])] = it.get("nomeOrgao") or ""
            time.sleep(0.4)
    _gravar_cache(instancia, {"data": hoje.isoformat(), "orgaos": achados})
    return achados


_trava_cache = threading.Lock()


def _ler_cache():
    try:
        with open(CACHE_ORGAOS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _gravar_cache(instancia, item):
    """Relê e grava sob trava, por arquivo temporário: TRF1, TR1 e TRU1 descobrem em
    paralelo (busca por grupo), e gravar o cache lido no começo apagava a instância
    que o vizinho acabara de gravar; leitor no meio da escrita via JSON cortado."""
    with _trava_cache:
        cache = _ler_cache()
        cache[instancia] = item
        os.makedirs(os.path.dirname(CACHE_ORGAOS), exist_ok=True)
        tmp = "%s.%d.tmp" % (CACHE_ORGAOS, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        for _ in range(40):  # no Windows, um leitor com o arquivo aberto barra o replace por instantes
            try:
                os.replace(tmp, CACHE_ORGAOS)
                return
            except PermissionError:
                time.sleep(0.025)
        os.replace(tmp, CACHE_ORGAOS)


def _por_orgao(instancia, frase, obrig, excl, ini, fim):
    """Busca a frase em cada órgão da instância (duas linhas paralelas)."""
    lista = orgaos(instancia)
    achados, vistos, cheios, falhas = [], set(), 0, 0

    def um(gid):
        time.sleep(0.4)
        return _get({"siglaTribunal": "TRF1", "texto": frase, "orgaoId": gid,
                     "dataDisponibilizacaoInicio": ini.isoformat(), "dataDisponibilizacaoFim": fim.isoformat(),
                     "itensPorPagina": 100, "pagina": 1})

    with ThreadPoolExecutor(max_workers=2) as ex:
        futuros = [ex.submit(um, g) for g in lista]
        for f in futuros:
            try:
                j = f.result()
            except Exception:
                falhas += 1
                continue
            itens = j.get("items") or []
            cheios += len(itens) >= 100
            for it in itens:
                achado = _acordao(it, instancia)
                if not achado:
                    continue
                julgado, id_acordao = achado
                chave = (julgado.processo, id_acordao or julgado.ementa[:80])
                corpo = _sem_acento(it.get("texto"))
                if chave in vistos or any(_sem_acento(o) not in corpo for o in obrig) \
                        or any(_sem_acento(x) in corpo for x in excl):
                    continue
                vistos.add(chave)
                achados.append(julgado)
    # a frase casa no inteiro teor (relatório e voto citam muita coisa de passagem): primeiro os
    # acórdãos cuja EMENTA traz todos os termos, depois algum termo; dentro de cada grupo, os mais recentes
    def peso(j):
        em = _sem_acento(j.ementa)
        n = sum(_sem_acento(o) in em for o in obrig)
        return (2 if n == len(obrig) else 1 if n else 0,
                j.data_publicacao[6:10] + j.data_publicacao[3:5] + j.data_publicacao[:2])
    achados.sort(key=peso, reverse=True)
    return achados, len(lista), cheios, falhas


def buscar(busca, maximo=10, dias=365, paginas=3, instancia="TRF1", profundo=True):
    """instancia: TRF1 (2º grau, desde mai/2025), TR1 (Turmas Recursais) ou TRU1."""
    obrig, excl = _termos(busca)
    if not obrig:
        return Resultado(fonte=FONTE, tribunal=instancia, busca=busca, erro="busca vazia")
    frase = max(obrig, key=len)
    res = Resultado(fonte=FONTE.replace("TRF1 – acórdãos", "%s – acórdãos" % instancia), tribunal=instancia,
                    busca="%s  [frase enviada ao DJEN: \"%s\"]" % (busca, frase))
    fim = dt.date.today()
    ini = fim - dt.timedelta(days=dias)
    if profundo:
        try:
            achados, n_gabs, cheios, falhas = _por_orgao(instancia, frase, obrig, excl, ini, fim)
            res.julgados = achados[:maximo]
            res.total = len(achados)
            res.total_e_minimo = cheios > 0
            alvo = {"TRF1": "gabinetes do 2º grau", "TR1": "órgãos das Turmas Recursais",
                    "TRU1": "órgãos da TRU1"}[instancia]
            res.aviso = (("DJEN, busca em cada um dos %d " + alvo + " (últimos %d dias): %d acórdãos distintos "
                         "com a frase; o total é mínimo quando algum órgão tem mais de 100 publicações com ela "
                         "(%d tiveram)%s. A data é a de publicação.") % (
                             n_gabs, dias, len(achados), cheios,
                             "; %d órgãos não responderam" % falhas if falhas else ""))
        except Exception as e:  # noqa: BLE001
            res.erro = "%s: %s" % (type(e).__name__, e)
        return res
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
                achado = _acordao(it, instancia)
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
        rotulo = {"TRF1": "do 2º grau", "TR1": "das Turmas Recursais", "TRU1": "da TRU1"}[instancia]
        res.aviso += ("DJEN: o total acima conta TODAS as comunicações do TRF1 com a frase (todas as instâncias, "
                      "repetidas por destinatário); foram examinadas %d, das quais %d acórdãos distintos %s. "
                      "Cobertura recente PARCIAL (busca por frase exata). A data é a de publicação."
                      % (varridos, len(res.julgados), rotulo))
    except Exception as e:  # noqa: BLE001
        res.erro = "%s: %s" % (type(e).__name__, e)
    return res
