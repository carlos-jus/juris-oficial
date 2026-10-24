# -*- coding: utf-8 -*-
"""juris-oficial – servidor MCP de pesquisa de jurisprudência nas fontes OFICIAIS:
STF, STJ, TNU, TRF1 a TRF6, Turmas Recursais e TRUs das seis regiões, e o BNP.

Execução: python servidor.py  (o instalador registra no Claude Code).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from juris_oficial import bnp, diagnostico, fontes  # noqa: E402
from juris_oficial.comum import markdown  # noqa: E402

mcp = FastMCP("juris-oficial")


@mcp.tool()
def pesquisar_jurisprudencia(busca: str, tribunais: str = "STF,STJ,TNU,TRF1", maximo: int = 5,
                             tipo: str = "acordao", ordem: str = "relevancia", completo: bool = False) -> str:
    """Pesquisa julgados nas bases OFICIAIS de cada tribunal, em paralelo, e devolve
    ementa LITERAL, órgão, relator, datas e link do inteiro teor de cada um.

    TRIBUNAIS (códigos separados por vírgula; grupos também valem):
      STF, STJ, TNU,
      TRF1, TRF2, TRF3, TRF4, TRF5, TRF6,
      TR1..TR6 (Turmas Recursais da região), TRU1..TRU6 (Turmas Regionais de Uniformização).
      Grupos: SUPERIORES (STF+STJ), TRFS (TRF1-6), JEF (TNU + TRUs), TRS (TR1-6), TRUS (TRU1-6).
      Ex.: "STJ,TRF1,TNU,TRU1,TR1" cobre a 1ª Região no JEF.

    BUSCA SIMPLES (traduzida para a sintaxe de cada base):
      - palavras soltas valem como E: auxílio-doença cessação perícia
      - "expressão exata" entre aspas: "acordo de não persecução penal"
      - conectores e / ou / não: "benefício assistencial" e miserabilidade não idoso
      - parênteses: (BPC ou LOAS) e "renda per capita"
      - curinga no fim da palavra: aposentad$ (ou aposentad*)
      Não passe perguntas em linguagem natural: extraia o instituto e os termos.

    tipo: "acordao" (padrão) ou "monocratica" (STF, STJ, TNU, TRF4, TRF6 e suas TRs/TRUs).
    ordem: "relevancia" (padrão) ou "data" (mais recentes primeiro; STF, STJ, eproc).
    maximo: julgados por tribunal (1-50). completo: true traz a ementa sem corte.

    COBERTURA E LIMITES (medidos em 24/10/2026; rode `listar_fontes` para o mapa):
      - TRF1: acórdãos desde mai/2025 vêm do DJEN (frase exata, data de publicação);
        até fev/2024, da base antiga do CJF. De mar/2024 a abr/2025 NÃO há fonte.
      - TR1/TRU1: base antiga do CJF, até ~ago/2026.
      - TRF5 (Julia): sem data de publicação e sem link do inteiro teor; total limitado a 10.000.
      - eproc (TNU, TRF2, TRF4, TRF6): nas Turmas Recursais, às vezes só a decisão vem no
        resultado – a ementa fica no inteiro teor (Link).
      Resultado ZERO numa fonte com aviso de limite não prova inexistência de julgado.

    Antes de citar em peça: confira a literalidade no inteiro teor (campo Link).
    """
    resultados = fontes.pesquisar(busca, tribunais, max(1, min(int(maximo), 50)), tipo, ordem)
    return "\n".join(markdown(r, completo) for r in resultados)


@mcp.tool()
def buscar_precedentes_qualificados(busca: str = "", orgaos: str = "STF,STJ", tipos: str = "RG,RR,SV,SUM",
                                    numero: str = "", maximo: int = 10) -> str:
    """Precedentes qualificados no Banco Nacional de Precedentes (BNP/CNJ): temas de
    repercussão geral (RG), repetitivos (RR), súmulas vinculantes (SV), súmulas (SUM),
    IRDR, IAC e PUIL, com a questão, a TESE e a situação do tema.

    busca: termos livres (ex.: "acordo de não persecução penal").
    numero: número do tema/súmula (ex.: numero="1098", orgaos="STJ", tipos="RR").
    orgaos: STF, STJ, TST, TNU, TRF1..TRF6, TJs... (separados por vírgula).
    Não traz julgados comuns: para eles, use `pesquisar_jurisprudencia`.
    """
    return markdown(bnp.buscar(busca, orgaos, tipos, max(1, min(int(maximo), 50)), numero), completo=True)


@mcp.tool()
def listar_fontes() -> str:
    """Mapa de cobertura: qual base oficial atende cada código de tribunal, desde quando
    e com que limites. Consulte antes de concluir que "não há julgado"."""
    linhas = ["| Código | Fonte e cobertura |", "|---|---|"]
    linhas += ["| %s | %s |" % (c, d) for c, (d, _) in fontes.FONTES.items()]
    faltam = [c for g in ("TRFS", "TRS", "TRUS") for c in fontes.GRUPOS[g] if c not in fontes.FONTES]
    if faltam:
        linhas.append("\nSem fonte automatizável: %s." % ", ".join(sorted(set(faltam))))
    return "\n".join(linhas)


@mcp.tool()
def diagnostico_fontes(tribunais: str = "TODOS") -> str:
    """Testa cada fonte com uma busca real e mostra se responde, o total e a data do
    julgado mais recente. Use quando uma fonte falhar ou para conferir a instalação."""
    return diagnostico.relatorio(tribunais)


if __name__ == "__main__":
    mcp.run()
