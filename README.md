# juris-oficial – pesquisa de jurisprudência nas fontes oficiais

Servidor MCP (para Claude Code e Claude Desktop) e linha de comando que pesquisam julgados
**direto nas bases oficiais de cada tribunal** e devolvem a ementa literal, o órgão, o relator,
as datas e o link do inteiro teor.

Cobre **STF, STJ, TNU, TRF1 a TRF6, as Turmas Recursais e as TRUs das seis regiões**, além dos
precedentes qualificados do **BNP/CNJ** (repercussão geral, repetitivos, súmulas, IRDR, IAC, PUIL).

## Por que existe

Em 23/10/2026 o CJF trocou o portal de jurisprudência (jurisprudencia.cjf.jus.br) por um que
**barra qualquer acesso automatizado**. A base antiga continua no ar, mas parada em vários pontos:
STJ em dez/2019, STF antes de 2017, TRF1 em fev/2024, Turmas Recursais de 3ª e 4ª Regiões em
2009-2013. Este pacote vai a cada tribunal pela fonte oficial que ainda responde.

## Fontes (medidas em 24/10/2026)

| Código | Fonte oficial | Cobertura |
|---|---|---|
| STF | jurisprudencia.stf.jus.br | todas as épocas – acórdãos, monocráticas, súmulas |
| STJ | scon.stj.jus.br (SCON) | todas as épocas – acórdãos e monocráticas |
| TNU | eproctnu-jur.cjf.jus.br + acervo do CJF | desde jul/2017 (eproc) + período anterior |
| TRF1 | DJEN (comunicaapi.pje.jus.br), gabinete por gabinete + base antiga do CJF | último ano + até fev/2024 – **lacuna mar/2024–abr/2025** |
| TR1, TRU1 | DJEN, órgão por órgão + base antiga do CJF (JEF1) | último ano + até ~ago/2026 (TR1) / ~mar/2025 (TRU1) |
| TRF2, TR2, TRU2 | eproc.trf2.jus.br | atual |
| TRF3, TR3, TRU3 | web.trf3.jus.br/jurisprudencia | atual (inclui as 17 Turmas Recursais de SP/MS) |
| TRF4, TR4, TRU4 | jurisprudencia.trf4.jus.br (eproc) | atual |
| TRF5, TR5, TRU5 | juliapesquisa.trf5.jus.br (Julia) | era PJe, atual; sem data de publicação nem link do inteiro teor |
| TRF6, TR6, TRU6 | eproc-jur.trf6.jus.br | atual |
| BNP | pangeabnp.pdpj.jus.br (CNJ) | precedentes qualificados de todos os tribunais |

## Instalação (Windows)

Requisitos: **Python 3.10+** (python.org, marcar "Add python.exe to PATH") e **Chrome ou Edge**
(usado, sem janela visível, só para STF e STJ).

1. Descompacte a pasta onde ela vai ficar (ex.: `Documentos\juris-oficial`).
2. Clique com o botão direito em `instalar.ps1` > **Executar com o PowerShell**.
   O instalador instala as dependências, registra o MCP no Claude Code e testa todas as fontes.
3. Reinicie o Claude Code.

Claude Desktop: o instalador imprime o trecho a colar em `%APPDATA%\Claude\claude_desktop_config.json`.

## Uso

No Claude, basta pedir: *"pesquise no STJ, no TRF1 e na TNU acordo de não persecução penal e
retroatividade"*. Ferramentas:

- `pesquisar_jurisprudencia(busca, tribunais, maximo, tipo, ordem, classe, relator, orgao)` – julgados,
  em paralelo; `classe`, `relator` e `orgao` filtram só nas bases eproc (TNU, TRF2, TRF4, TRF6 e suas
  Turmas Recursais e TRUs; a TNU não tem o de órgão), pelo nome como a base o escreve (sem diferenciar
  caixa nem acento, e com todas as grafias que a base tiver do mesmo nome), e nome que não existe volta
  como erro com os mais parecidos;
- `buscar_precedentes_qualificados(busca, orgaos, tipos, numero)` – temas e súmulas (BNP);
- `listar_fontes()` – o mapa de cobertura acima;
- `diagnostico_fontes()` – testa cada base ao vivo.

Grupos de tribunais: `SUPERIORES`, `TRFS`, `JEF` (TNU + TRUs), `TRS`, `TRUS`.

Busca simples: palavras (valem como "e"), `"expressão exata"`, `e` / `ou` / `não`, parênteses e
curinga no fim (`aposentad$`). A ferramenta traduz para a sintaxe de cada tribunal.

Linha de comando (sem MCP):

```
python -m juris_oficial "\"benefício assistencial\" e miserabilidade" --tribunais JEF --maximo 3
python -m juris_oficial --precedentes "acordo de não persecução penal"
python -m juris_oficial.diagnostico
```

## Limites que importam

- **Zero não prova inexistência** quando a fonte tem limite declarado (TRF1 entre mar/2024 e
  abr/2025; 1ª Região pelo DJEN só por frase exata; Julia com teto de 10.000).
- **1ª Região é mais lenta** (~50 s por tribunal): o DJEN não filtra por instância, então a busca
  passa por cada gabinete ou relatoria. A primeira vez descobre a lista de órgãos (~1 min por
  instância) e a guarda por 30 dias.
- **Confira a literalidade no inteiro teor** antes de citar. A ementa vem literal da base, mas a
  base pode ter erro de digitação ou corte.
- Os sítios dos tribunais mudam sem aviso. Rode `diagnostico_fontes` quando algo falhar e
  atualize o pacote.
- Seja moderado no volume: as bases são públicas e algumas limitam requisições.

## Atualização

Os tribunais mudam seus sítios sem aviso; as correções saem em novas versões.

- Quem clonou com git: `git pull` na pasta e reinicie o Claude.
- Quem baixou o zip: baixe a versão nova na página de *Releases*, substitua a pasta e rode
  `instalar.ps1` de novo.

Problema numa fonte? Rode `python -m juris_oficial.diagnostico` e abra uma *issue* com a tabela.

## Aviso

Projeto independente e sem vínculo oficial com nenhum tribunal, conselho ou instituição. Usa só
as consultas públicas que os próprios tribunais oferecem.

## Privacidade

O pacote não pede login nem senha e só acessa bases públicas; guarda apenas a lista de órgãos do
DJEN (`%LOCALAPPDATA%\juris-oficial\orgaos_djen_trf1.json`). O navegador usado para STF/STJ tem
perfil próprio, novo e vazio a cada abertura (dentro de `%LOCALAPPDATA%\juris-oficial\perfis`),
separado do seu. O perfil único das versões até a 1.0.1 (`...\juris-oficial\navegador`) é
apagado sozinho na primeira busca no STF ou no STJ.

## O navegador do STF/STJ

- Abre na primeira busca no STF ou no STJ e **fecha sozinho** depois de 3 minutos sem busca
  (`JURIS_OFICIAL_OCIOSO_S`, em segundos; `0` fecha ao fim de cada busca). Aberto, ocupa cerca de
  0,5 GB; reabrir custa uns 10 s na busca seguinte.
- No Windows, ele morre junto com o servidor, mesmo se o servidor for encerrado à força.
- A porta de depuração é uma porta livre escolhida na hora e só escuta em `127.0.0.1`.
