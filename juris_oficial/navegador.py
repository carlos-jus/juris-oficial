# -*- coding: utf-8 -*-
"""Navegador próprio do juris-oficial, para as bases que só respondem a navegador real.

O SCON do STJ (Cloudflare) e a base do STF (WAF da AWS) recusam `requests`, mas
aceitam o `fetch` disparado de DENTRO de uma página aberta num Chrome ou Edge de
verdade: mesma origem, cookies reais. Este módulo sobe um navegador SEPARADO do
que a pessoa usa (perfil próprio, novo a cada abertura, dentro de
%LOCALAPPDATA%\\juris-oficial\\navegador) e conversa com ele pelo protocolo DevTools (CDP).

Nada de login, nada de dado pessoal: o perfil nasce vazio e só visita bases
públicas de jurisprudência.

Ciclo de vida (o navegador ocupa ~0,5 GB e não pode sobrar):
- fecha sozinho depois de JURIS_OFICIAL_OCIOSO_S segundos sem busca (padrão 180;
  0 = fecha ao fim de cada busca). Abrir de novo custa ~3 s + o desafio do portal
  (~8 s), por isso o padrão não é fechar a cada busca;
- no Windows, nasce dentro de um Job Object que o mata junto com este processo:
  servidor morto não deixa navegador órfão;
- a porta de depuração é efêmera (escolhida pelo próprio navegador), só em 127.0.0.1.
"""
import atexit
import contextlib
import ctypes
import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request

import websocket  # websocket-client

PERFIL = os.environ.get("JURIS_OFICIAL_PERFIL") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "juris-oficial", "navegador")
# Modo da janela: "discreto" (padrão: janela real, mas fora da área visível da tela),
# "visivel" (para depurar) ou "oculto" (headless – o Cloudflare do STJ NÃO passa assim).
MODO = os.environ.get("JURIS_OFICIAL_NAVEGADOR_MODO", "discreto")
OCIOSO_S = float(os.environ.get("JURIS_OFICIAL_OCIOSO_S", "180"))

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


def vivo(porta):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/json/version" % porta, timeout=2).read()
        return True
    except Exception:
        return False


_trava = threading.RLock()
_proc = None      # o navegador (Popen)
_job = None       # Job Object que o mata junto com este processo (Windows)
_porta = None
_perfil = None    # pasta do perfil desta abertura; apagada ao fechar
_geracao = 0      # muda a cada abertura: aba de um navegador já fechado não vale
_em_uso = 0
_relogio = None   # fechamento por ociosidade


class _Limites(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32), ("IoCounters", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def _lancar(args):
    """Popen do navegador. No Windows ele nasce suspenso, entra num Job Object com
    KILL_ON_JOB_CLOSE e só então roda: ele e todos os filhos morrem quando o último
    handle do job fecha, o que o sistema faz sozinho quando este processo morre."""
    opcoes = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name != "nt":
        # shortcut: fora do Windows o navegador não morre com o servidor; subir para prctl/PDEATHSIG se alguém usar
        return subprocess.Popen(args, **opcoes), None
    k = _kernel32()
    job = k.CreateJobObjectW(None, None)
    limites = _Limites(LimitFlags=0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not k.SetInformationJobObject(job, 9, ctypes.byref(limites), ctypes.sizeof(limites)):
        raise NavegadorIndisponivel("não consegui criar o Job Object (erro %d)" % ctypes.get_last_error())
    # CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    p = subprocess.Popen(args, creationflags=0x4 | 0x200 | 0x08000000, **opcoes)
    amarrado = k.AssignProcessToJobObject(job, int(p._handle))
    erro = ctypes.get_last_error()
    if not amarrado:
        p.kill()
    ctypes.WinDLL("ntdll").NtResumeProcess(ctypes.c_void_p(int(p._handle)))
    if not amarrado:
        k.CloseHandle(job)
        raise NavegadorIndisponivel("não consegui amarrar o navegador a este processo (erro %d)" % erro)
    return p, job


def _ler_porta(perfil, proc, espera):
    """A porta efêmera que o navegador escolheu (--remote-debugging-port=0) sai no
    arquivo DevToolsActivePort do perfil."""
    arquivo = os.path.join(perfil, "DevToolsActivePort")
    fim = time.time() + espera
    while time.time() < fim:
        if proc.poll() is not None:
            raise NavegadorIndisponivel("o navegador saiu logo ao abrir (código %s)" % proc.returncode)
        try:
            with open(arquivo, encoding="utf-8") as f:
                porta = int(f.readline().strip())
            if vivo(porta):
                return porta
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    raise NavegadorIndisponivel("o navegador não abriu a porta de depuração em %d s" % espera)


def _apagar_perfis_velhos():
    """Perfis de aberturas que não fecharam limpo (processo morto) com mais de 1 dia."""
    for d in glob.glob(os.path.join(PERFIL, "perfil-*")):
        with contextlib.suppress(OSError):
            if time.time() - os.path.getmtime(d) > 86400:
                shutil.rmtree(d, ignore_errors=True)


def garantir(espera=30):
    """Sobe o navegador próprio se ele ainda não estiver no ar; devolve a porta."""
    global _proc, _job, _porta, _perfil, _geracao
    with _trava:
        if _proc is not None and _proc.poll() is None and vivo(_porta):
            return _porta
        encerrar()
        os.makedirs(PERFIL, exist_ok=True)
        _apagar_perfis_velhos()
        _perfil = tempfile.mkdtemp(prefix="perfil-", dir=PERFIL)
        args = [_executavel(), "--remote-debugging-port=0", "--user-data-dir=" + _perfil,
                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                "--disable-background-networking", "--lang=pt-BR"]
        if MODO == "oculto":
            args += ["--headless=new", "--window-size=1366,900"]
        elif MODO == "discreto":
            args += ["--window-position=-32000,-32000", "--window-size=1366,900"]
        args.append("about:blank")
        _proc, _job = _lancar(args)
        try:
            _porta = _ler_porta(_perfil, _proc, espera)
        except Exception:
            encerrar()
            raise
        _geracao += 1
        return _porta


def encerrar():
    """Fecha o navegador próprio (todos os processos) e apaga o perfil desta abertura."""
    global _proc, _job, _porta, _perfil, _relogio
    with _trava:
        if _relogio is not None:
            _relogio.cancel()
            _relogio = None
        if _job is not None:
            k = _kernel32()
            k.TerminateJobObject(_job, 0)
            k.CloseHandle(_job)
        elif _proc is not None and _proc.poll() is None:
            _proc.terminate()
        if _proc is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                _proc.wait(10)
        if _perfil:
            for _ in range(20):  # os filhos soltam os arquivos do perfil logo depois do pai
                shutil.rmtree(_perfil, ignore_errors=True)
                if not os.path.exists(_perfil):
                    break
                time.sleep(0.25)
        _proc = _job = _porta = _perfil = None


atexit.register(encerrar)  # saída limpa: fecha e apaga o perfil (saída à força: o job fecha)


def _fechar_se_ocioso():
    with _trava:
        if _em_uso == 0:
            encerrar()


@contextlib.contextmanager
def em_uso():
    """Envolve cada busca: o navegador não fecha no meio dela e, ao fim da última
    (com ou sem erro), arma o fechamento por ociosidade."""
    global _em_uso, _relogio
    with _trava:
        _em_uso += 1
        if _relogio is not None:
            _relogio.cancel()
            _relogio = None
    try:
        yield
    finally:
        with _trava:
            _em_uso -= 1
            if _em_uso == 0 and _proc is not None:
                if OCIOSO_S <= 0:
                    encerrar()
                else:
                    _relogio = threading.Timer(OCIOSO_S, _fechar_se_ocioso)
                    _relogio.daemon = True
                    _relogio.start()


class Aba:
    """Uma aba nova no navegador próprio; fecha sozinha no `with`."""

    def __init__(self):
        porta = garantir()
        self.geracao = _geracao
        self.porta = porta
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % porta, method="PUT")
        alvo = json.loads(urllib.request.urlopen(req, timeout=15).read())
        self.id = alvo["id"]
        self.ws = websocket.create_connection(alvo["webSocketDebuggerUrl"], timeout=120,
                                              suppress_origin=True)
        self._n = 0

    def valida(self):
        """Falso se o navegador desta aba já foi fechado (por ociosidade ou erro)."""
        return self.geracao == _geracao and _proc is not None and _proc.poll() is None

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
