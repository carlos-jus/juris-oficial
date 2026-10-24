# -*- coding: utf-8 -*-
"""Navegador próprio do juris-oficial, para as bases que só respondem a navegador real.

O SCON do STJ (Cloudflare) e a base do STF (WAF da AWS) recusam `requests`, mas
aceitam o `fetch` disparado de DENTRO de uma página aberta num Chrome ou Edge de
verdade: mesma origem, cookies reais. Este módulo sobe um navegador SEPARADO do
que a pessoa usa (perfil próprio em %LOCALAPPDATA%\\juris-oficial\\navegador, porta de
depuração própria) e conversa com ele pelo protocolo DevTools (CDP).

Nada de login, nada de dado pessoal: o perfil nasce vazio e só visita bases
públicas de jurisprudência.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

import websocket  # websocket-client

PORTA = int(os.environ.get("JURIS_OFICIAL_PORTA", "9333"))
PERFIL = os.environ.get("JURIS_OFICIAL_PERFIL") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "juris-oficial", "navegador")
# Modo da janela: "discreto" (padrão: janela real, mas fora da área visível da tela),
# "visivel" (para depurar) ou "oculto" (headless – o Cloudflare do STJ NÃO passa assim).
MODO = os.environ.get("JURIS_OFICIAL_NAVEGADOR_MODO", "discreto")

CANDIDATOS = [
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


class NavegadorIndisponivel(RuntimeError):
    pass


def _executavel():
    escolhido = os.environ.get("JURIS_OFICIAL_NAVEGADOR")
    if escolhido and os.path.exists(escolhido):
        return escolhido
    for c in CANDIDATOS:
        if os.path.exists(c):
            return c
    for nome in ("chrome", "google-chrome", "chromium", "msedge"):
        achado = shutil.which(nome)
        if achado:
            return achado
    raise NavegadorIndisponivel(
        "Não achei Chrome nem Edge. Instale um deles ou aponte o caminho em JURIS_OFICIAL_NAVEGADOR.")


def vivo(porta=PORTA):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/json/version" % porta, timeout=2).read()
        return True
    except Exception:
        return False


def garantir(porta=PORTA, espera=30):
    """Sobe o navegador próprio se ele ainda não estiver no ar."""
    if vivo(porta):
        return
    os.makedirs(PERFIL, exist_ok=True)
    args = [_executavel(), "--remote-debugging-port=%d" % porta, "--user-data-dir=" + PERFIL,
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--lang=pt-BR"]
    if MODO == "oculto":
        args += ["--headless=new", "--window-size=1366,900"]
    elif MODO == "discreto":
        args += ["--window-position=-32000,-32000", "--window-size=1366,900"]
    args.append("about:blank")
    opcoes = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        opcoes["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen(args, **opcoes)
    fim = time.time() + espera
    while time.time() < fim:
        if vivo(porta):
            return
        time.sleep(0.5)
    raise NavegadorIndisponivel("O navegador não abriu a porta %d em %d s." % (porta, espera))


class Aba:
    """Uma aba nova no navegador próprio; fecha sozinha no `with`."""

    def __init__(self, porta=PORTA):
        garantir(porta)
        self.porta = porta
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % porta, method="PUT")
        alvo = json.loads(urllib.request.urlopen(req, timeout=15).read())
        self.id = alvo["id"]
        self.ws = websocket.create_connection(alvo["webSocketDebuggerUrl"], timeout=120,
                                              suppress_origin=True)
        self._n = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()

    def cmd(self, metodo, timeout=120, **params):
        self._n += 1
        n = self._n
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": n, "method": metodo, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == n:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (metodo, msg["error"]))
                return msg.get("result", {})

    def js(self, expressao, timeout=120):
        r = self.cmd("Runtime.evaluate", timeout=timeout, expression=expressao,
                     awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: %s" % r["exceptionDetails"].get("text"))
        return r.get("result", {}).get("value")

    def ir(self, url, pronto_quando=None, espera=60):
        """Navega e espera a página carregar; `pronto_quando` é uma função(título)->bool
        para desafios (ex.: Cloudflare "Um momento…")."""
        self.cmd("Page.enable")
        self.cmd("Page.navigate", url=url)
        fim = time.time() + espera
        while time.time() < fim:
            time.sleep(1)
            try:
                estado = self.js("document.readyState + '|' + document.title", timeout=10) or ""
            except Exception:
                continue
            pronto, _, titulo = estado.partition("|")
            if pronto == "complete" and (pronto_quando is None or pronto_quando(titulo)):
                return titulo
        raise NavegadorIndisponivel("A página não ficou pronta em %d s: %s" % (espera, url))

    def buscar(self, caminho, metodo="GET", corpo=None, cabecalhos=None, codificacao="utf-8", timeout=90):
        """`fetch` de dentro da página (mesma origem). Devolve (status, texto)."""
        opcoes = {"method": metodo, "credentials": "include", "headers": cabecalhos or {}}
        if corpo is not None:
            opcoes["body"] = corpo
        expr = ("(async () => { const r = await fetch(%s, %s); const b = await r.arrayBuffer();"
                " return r.status + '|' + new TextDecoder(%s).decode(b); })()"
                % (json.dumps(caminho), json.dumps(opcoes), json.dumps(codificacao)))
        bruto = self.js(expr, timeout=timeout) or "0|"
        status, _, texto = bruto.partition("|")
        return int(status or 0), texto

    def fechar(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/json/close/%s" % (self.porta, self.id), timeout=5)
        except Exception:
            pass
