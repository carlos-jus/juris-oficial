# -*- coding: utf-8 -*-
"""Despachante: cada código de tribunal -> a melhor fonte oficial automatizável
(mapa medido em 24/10/2026), e a pesquisa em paralelo em vários deles."""
import re
from concurrent.futures import ThreadPoolExecutor

from . import cjf_antigo, djen, eproc, stf, stj, trf3, trf5
from .comum import Resultado

# código -> (descrição da cobertura, função)
def _eproc(trib):
    return lambda busca, maximo, tipo, ordem: eproc.buscar(trib, busca, maximo, tipo=tipo, ordem=ordem)


def _numero(j):
    return re.sub(r"\D", "", j.processo)[:20]


def _juntar(principal, complemento, rotulo):
    """Une duas fontes do mesmo tribunal, sem repetir processo."""
    if principal.erro and not complemento.erro:
        principal, complemento = complemento, principal
    vistos = {_numero(j) for j in principal.julgados}
    extra = [j for j in complemento.julgados if _numero(j) not in vistos]
    principal.julgados += extra
    avisos = [principal.aviso, complemento.aviso,
              "%s: %s" % (rotulo, ("FALHOU – " + complemento.erro) if complemento.erro else
                          "total %s, %d acrescentados sem repetir processo" % (complemento.total, len(extra)))]
    principal.aviso = " | ".join(a for a in avisos if a)
    principal.fonte += " + " + complemento.fonte
    return principal


def _tnu(busca, maximo, tipo, ordem):
    novo = eproc.buscar("TNU", busca, maximo, tipo=tipo, ordem=ordem)
    if tipo != "acordao":
        return novo
    return _juntar(novo, cjf_antigo.buscar("TNU", busca, maximo), "acervo da TNU no CJF")


def _trf1(busca, maximo, tipo, ordem):
    recente = djen.buscar(busca, maximo)
    return _juntar(recente, cjf_antigo.buscar("TRF1", busca, maximo), "TRF1 até fev/2024 (CJF)")


def _jef1(trib, ate):
    def f(busca, maximo, tipo, ordem):
        recente = djen.buscar(busca, maximo, instancia=trib)
        return _juntar(recente, cjf_antigo.buscar(trib, busca, maximo), "%s até %s (CJF)" % (trib, ate))
    return f


FONTES = {
    "STF": ("STF – base oficial (todas as épocas)",
            lambda b, m, t, o: stf.buscar(b, m, tipo=t, ordem=o)),
    "STJ": ("STJ – SCON (todas as épocas)",
            lambda b, m, t, o: stj.buscar(b, m, tipo=t, ordem=o)),
    "TNU": ("TNU – eproc (desde jul/2017) + acervo do CJF", _tnu),
    "TRF1": ("TRF1 – DJEN por gabinete (último ano) + CJF (até fev/2024); LACUNA mar/2024–abr/2025", _trf1),
    "TR1": ("Turmas Recursais da 1ª Região – DJEN por relatoria (último ano) + CJF/JEF1 (até ~ago/2026)",
            _jef1("TR1", "~ago/2026")),
    "TRU1": ("TRU da 1ª Região – DJEN por órgão (último ano) + CJF/JEF1 (até ~mar/2025)",
             _jef1("TRU1", "~mar/2025")),
    "TRF2": ("TRF2 – eproc", _eproc("TRF2")),
    "TR2": ("Turmas Recursais do RJ/ES – eproc", _eproc("TR2")),
    "TRU2": ("TRU da 2ª Região – eproc", _eproc("TRU2")),
    "TRF3": ("TRF3 – pesquisa oficial", lambda b, m, t, o: trf3.buscar("TRF3", b, m)),
    "TR3": ("Turmas Recursais de SP/MS (com a TRU3) – pesquisa oficial do TRF3",
            lambda b, m, t, o: trf3.buscar("TR3", b, m)),
    "TRU3": ("TRU da 3ª Região – pesquisa oficial do TRF3", lambda b, m, t, o: trf3.buscar("TRU3", b, m)),
    "TRF4": ("TRF4 – eproc", _eproc("TRF4")),
    "TR4": ("Turmas Recursais da 4ª Região – eproc", _eproc("TR4")),
    "TRU4": ("TRU da 4ª Região – eproc", _eproc("TRU4")),
    "TRF5": ("TRF5 – Julia", lambda b, m, t, o: trf5.buscar("TRF5", b, m)),
    "TR5": ("Turmas Recursais da 5ª Região – Julia", lambda b, m, t, o: trf5.buscar("TR5", b, m)),
    "TRU5": ("TRU da 5ª Região – Julia", lambda b, m, t, o: trf5.buscar("TRU5", b, m)),
    "TRF6": ("TRF6 – eproc", _eproc("TRF6")),
    "TR6": ("Turmas Recursais de MG – eproc", _eproc("TR6")),
    "TRU6": ("TRU da 6ª Região – eproc", _eproc("TRU6")),
}

GRUPOS = {
    "SUPERIORES": ["STF", "STJ"],
    "TRFS": ["TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6"],
    "JEF": ["TNU", "TRU1", "TRU2", "TRU3", "TRU4", "TRU5", "TRU6"],
    "TRS": ["TR1", "TR2", "TR3", "TR4", "TR5", "TR6"],
    "TRUS": ["TRU1", "TRU2", "TRU3", "TRU4", "TRU5", "TRU6"],
}


def codigos(tribunais):
    saida = []
    for t in re.split(r"[,;\s]+", (tribunais or "").upper()):
        if not t:
            continue
        for c in GRUPOS.get(t, [t]):
            if c not in saida:
                saida.append(c)
    return saida


EPROC = {c for _, origens, _ in eproc.INSTANCIAS.values() for c in origens}


def pesquisar(busca, tribunais="STF,STJ,TNU,TRF1", maximo=5, tipo="acordao", ordem="relevancia",
              classe="", relator="", orgao=""):
    alvos = codigos(tribunais)
    filtros = {"classe": classe, "relator": relator, "orgao": orgao}
    filtros = {p: v for p, v in filtros.items() if v and v.strip()}

    def um(cod):
        if cod not in FONTES:
            return Resultado(fonte="-", tribunal=cod, busca=busca,
                             erro="tribunal sem fonte automatizável configurada (códigos válidos: %s)"
                                  % ", ".join(FONTES))
        try:
            if filtros and cod in EPROC:
                # direto no eproc: o acervo antigo que a TNU junta (CJF) não tem estes filtros
                res = eproc.buscar(cod, busca, maximo, tipo=tipo, ordem=ordem, **filtros)
                if cod == "TNU" and not res.erro:
                    res.aviso += " | filtro aplicado só ao eproc; o acervo anterior do CJF não foi consultado"
                return res
            res = FONTES[cod][1](busca, maximo, tipo, ordem)
            if filtros and not res.erro:
                aviso = ("filtro (%s) não se aplica a esta base (só eproc: TNU, TRF2, TRF4, TRF6 e "
                         "suas TRs/TRUs); a busca saiu sem ele" % ", ".join(filtros))
                res.aviso = (res.aviso + " | " if res.aviso else "") + aviso
            return res
        except Exception as e:  # noqa: BLE001
            return Resultado(fonte=FONTES[cod][0], tribunal=cod, busca=busca, erro="%s: %s" % (type(e).__name__, e))

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(alvos)))) as ex:
        return list(ex.map(um, alvos))
