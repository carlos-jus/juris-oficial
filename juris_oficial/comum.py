# -*- coding: utf-8 -*-
"""Peças comuns a todas as fontes: o formato do resultado, a limpeza de HTML e a
tradução da busca simples para a sintaxe de cada base."""
import html as htmlmod
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


@dataclass
class Julgado:
    tribunal: str                     # STJ, STF, TNU, TRF1..TRF6, TRU1..TRU6, TR1..TR6
    processo: str = ""
    classe: str = ""
    orgao: str = ""
    relator: str = ""
    data_julgamento: str = ""
    data_publicacao: str = ""
    tipo: str = ""                    # acórdão, decisão monocrática, súmula...
    ementa: str = ""
    decisao: str = ""
    tese: str = ""
    link: str = ""                    # inteiro teor (ou a melhor URL estável disponível)
    citacao: str = ""                 # referência pronta, quando a base fornece
    fonte: str = ""                   # base consultada


@dataclass
class Resultado:
    fonte: str
    tribunal: str
    busca: str
    total: Optional[int] = None
    total_e_minimo: bool = False      # a base só informa "10.000 ou mais"
    julgados: List[Julgado] = field(default_factory=list)
    aviso: str = ""
    erro: str = ""

    def dict(self):
        return asdict(self)


def texto(fragmento: str) -> str:
    """HTML -> texto, preservando as quebras de parágrafo."""
    if not fragmento:
        return ""
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", fragmento, flags=re.I)
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S | re.I)
    # marcas de destaque do termo pesquisado (span, b, em, font, mark...) saem SEM deixar
    # espaço: "<span>PRIVILEGIADO</span>." tem de continuar "PRIVILEGIADO." (literalidade)
    t = re.sub(r"</?(?:span|b|strong|em|i|u|font|mark|a)\b[^>]*>", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{2,}", "\n", t).strip()


def linha(fragmento: str) -> str:
    return re.sub(r"\s+", " ", texto(fragmento)).strip()


# ---------------------------------------------------------------------------
# Busca simples -> sintaxe de cada base
# ---------------------------------------------------------------------------
# A busca simples aceita: palavras, "expressões entre aspas", os conectores
# e / ou / não (em qualquer caixa, com ou sem acento), parênteses e o curinga
# no fim da palavra ($ ou *). Palavras soltas valem como "e".

_TOKEN = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')
_CONECTORES = {"e": "E", "and": "E", "ou": "OU", "or": "OU",
               "nao": "NAO", "não": "NAO", "not": "NAO"}

# conector -> como cada sintaxe escreve; curinga de cada sintaxe
SINTAXES = {
    "scon":  ({"E": "e", "OU": "ou", "NAO": "nao"}, "$"),      # STJ
    "stf":   ({"E": "AND", "OU": "OR", "NAO": "NOT"}, "*"),    # STF (Elasticsearch)
    "eproc": ({"E": "e", "OU": "ou", "NAO": "não"}, "*"),      # TNU, TRF2, TRF4, TRF6
    "julia": ({"E": "e", "OU": "ou", "NAO": "nao"}, "$"),      # TRF5
    "trf3":  ({"E": "e", "OU": "ou", "NAO": "não"}, "$"),      # TRF3
    "cjf":   ({"E": "E", "OU": "OU", "NAO": "NAO"}, "$"),      # base antiga do CJF
}


def traduzir(busca: str, sintaxe: str) -> str:
    """Converte a busca simples. Operadores próprios da base (adj, prox, [EMEN]...)
    passam como estão – quem os usa assume a sintaxe daquela base."""
    conectores, curinga = SINTAXES[sintaxe]
    saida, anterior_termo = [], False
    for tok in _TOKEN.findall(busca or ""):
        chave = tok.lower()
        if chave in _CONECTORES:
            saida.append(conectores[_CONECTORES[chave]])
            anterior_termo = False
            continue
        if tok == ")":
            saida.append(tok)
            anterior_termo = True
            continue
        if anterior_termo and tok != ")":
            saida.append(conectores["E"])
        if tok == "(":
            saida.append(tok)
            anterior_termo = False
            continue
        if not tok.startswith('"') and tok[-1:] in ("$", "*"):
            tok = tok[:-1] + curinga
        saida.append(tok)
        anterior_termo = True
    return " ".join(saida).replace("( ", "(").replace(" )", ")")


def recorte(t: str, n: int = 900) -> str:
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " [...]"


def markdown(res: "Resultado", completo: bool = False, limite_ementa: int = 1200) -> str:
    """Saída legível para o modelo e para a pessoa."""
    cab = "## %s – %s\n" % (res.tribunal, res.fonte)
    if res.erro:
        return cab + "**FALHOU:** %s\n" % res.erro
    tot = ("%s%s" % ("≥ " if res.total_e_minimo else "", "{:,}".format(res.total).replace(",", "."))
           if res.total is not None else "?")
    partes = [cab, "Busca: `%s` | total na base: **%s** | trazidos: %d\n" % (res.busca, tot, len(res.julgados))]
    if res.aviso:
        partes.append("> %s\n" % res.aviso)
    for i, j in enumerate(res.julgados, 1):
        ident = " ".join(x for x in (j.classe, j.processo) if x) or "(sem número)"
        partes.append("\n### %d. %s – %s" % (i, j.tribunal, ident))
        meta = [("Órgão", j.orgao), ("Relator", j.relator), ("Julgamento", j.data_julgamento),
                ("Publicação", j.data_publicacao), ("Tipo", j.tipo), ("Link", j.link)]
        partes.append("\n".join("- **%s:** %s" % (k, v) for k, v in meta if v))
        if j.tese:
            partes.append("- **Tese:** %s" % j.tese)
        corpo = j.ementa or j.decisao
        if corpo:
            partes.append("\n**%s (literal):**\n%s" % ("Ementa" if j.ementa else "Decisão",
                                                       corpo if completo else recorte(corpo, limite_ementa)))
        if j.citacao:
            partes.append("\n*Referência fornecida pela base:* %s" % j.citacao)
    return "\n".join(partes) + "\n"
