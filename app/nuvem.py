"""Banco na nuvem (Turso): réplica local sincronizada com o banco remoto.

Ligado quando o .env tem TURSO_DATABASE_URL e TURSO_AUTH_TOKEN. Sem eles, o CRM usa o crm.db local de sempre.
Leituras vêm da réplica local (rápidas); gravações vão para o Turso e voltam para a réplica na hora.
O cliente libsql não tem row_factory nem as exceções do sqlite3: as classes abaixo imitam o que o resto do código usa.
"""
import datetime as dt
import os
import re
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERVALO_SYNC = 300   # segundos entre sincronizações em segundo plano (puxa alterações feitas em outro aparelho)


def carregar_env(arquivo: Path = ROOT / ".env") -> None:
    """Lê KEY=VALOR do .env para os.environ (sem sobrescrever o que já existe). Sem dependência extra."""
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env()
URL = os.environ.get("TURSO_DATABASE_URL", "")
TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
# CRM_BANCO=libsql: usa o cliente libsql sem sincronizar (só para rodar os testes com o adaptador)
SO_ADAPTADOR = os.environ.get("CRM_BANCO") == "libsql"
status = {"ultima_sync": None, "erro": None}   # mostrado em Dados e nos alertas


def ativo() -> bool:
    return bool(URL and TOKEN) or SO_ADAPTADOR


# ---------- imitação de sqlite3.Row / Cursor / Connection ----------
class Linha:
    """Equivale a sqlite3.Row: r[0], r["coluna"] (sem diferenciar maiúsculas), keys(), dict(r)."""
    __slots__ = ("_nomes", "_cols", "_vals")

    def __init__(self, nomes: list, cols: dict, vals: tuple):
        self._nomes, self._cols, self._vals = nomes, cols, vals

    def __getitem__(self, k):
        if isinstance(k, (int, slice)):
            return self._vals[k]
        i = self._cols.get(k)
        if i is None:
            i = self._cols.get(str(k).lower())
        if i is None:
            raise IndexError(f"No item with that key: {k}")
        return self._vals[i]

    def keys(self):
        return list(self._nomes)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __eq__(self, outra):
        return isinstance(outra, Linha) and self._vals == outra._vals

    def __repr__(self):
        return f"Linha({dict(zip(self.keys(), self._vals))})"


_NOMEADO = re.compile(r"'(?:[^']|'')*'|:([A-Za-z_]\w*)")


def _posicional(sql: str, params):
    """libsql só aceita parâmetros posicionais: troca :nome por ? e monta a tupla na ordem (ignora texto entre aspas)."""
    if not isinstance(params, dict):
        return sql, tuple(params)
    ordem = []

    def troca(m):
        if m.group(1) is None:
            return m.group(0)
        ordem.append(params[m.group(1)])
        return "?"
    return _NOMEADO.sub(troca, sql), tuple(ordem)


def _erro(e: Exception) -> Exception:
    msg = str(e)
    if "constraint failed" in msg:
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


class Cursor:
    def __init__(self, bruto):
        self._c = bruto
        self._nomes = self._cols = None

    def _linha(self, vals):
        if vals is None:
            return None
        if self._cols is None:
            self._nomes = [d[0] for d in self._c.description or ()]
            self._cols = {}
            for i, nome in enumerate(self._nomes):
                self._cols.setdefault(nome, i)              # como o sqlite3.Row: vale a 1ª coluna com o nome
                self._cols.setdefault(nome.lower(), i)
        return Linha(self._nomes, self._cols, tuple(vals))

    def fetchone(self):
        return self._linha(self._c.fetchone())

    def fetchall(self):
        return [self._linha(v) for v in self._c.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self._c.lastrowid

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def description(self):
        return self._c.description


class Conexao:
    """Uma requisição por vez usa a conexão compartilhada (trava liberada no close)."""
    row_factory = None   # aceita a atribuição de quem espera sqlite3; as linhas já vêm como Linha

    def __init__(self, bruta, trava):
        self._c, self._trava, self._aberta = bruta, trava, True

    def execute(self, sql, params=()):
        try:
            return Cursor(self._c.execute(*_posicional(sql, params)))
        except ValueError as e:
            raise _erro(e) from e

    def executemany(self, sql, seq):
        try:
            seq = list(seq)
            if seq and isinstance(seq[0], dict):
                novo = _posicional(sql, seq[0])[0]
                return Cursor(self._c.executemany(novo, [_posicional(sql, p)[1] for p in seq]))
            return Cursor(self._c.executemany(sql, [tuple(p) for p in seq]))
        except ValueError as e:
            raise _erro(e) from e

    def executescript(self, sql):
        try:
            self._c.executescript(sql)
        except ValueError as e:
            raise _erro(e) from e

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    @property
    def in_transaction(self):
        return self._c.in_transaction

    def __enter__(self):
        return self

    def __exit__(self, tipo, *_):
        if tipo is None:
            self.commit()
        else:
            self.rollback()
        return False

    def close(self):
        if self._aberta:
            self._aberta = False
            if self._c.in_transaction:
                self._c.rollback()
            if self._trava is None:   # conexão própria (modo de teste): fecha de verdade
                self._c.close()
            else:
                self._trava.release()


# ---------- conexão compartilhada por arquivo ----------
_brutas: dict = {}
_travas: dict = {}
_guarda = threading.Lock()


def _bruta(caminho: Path):
    try:
        import libsql   # só importado quando o modo nuvem está ligado
    except ImportError:
        if sys.version_info >= (3, 14) and sys.platform == "win32":
            raise RuntimeError("a biblioteca do Turso ainda não funciona no Python 3.14 do Windows: recrie a pasta .venv "
                               "com o Python 3.13 (README, seção Banco na nuvem) ou apague o .env para usar o banco local") from None
        raise RuntimeError("falta a biblioteca do Turso: rode .venv\\Scripts\\python.exe -m pip install -r requirements.txt") from None
    chave = str(caminho)
    with _guarda:
        if chave not in _brutas:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            _brutas[chave] = libsql.connect(chave, sync_url=URL, auth_token=TOKEN, _check_same_thread=False)
            _travas[chave] = threading.Lock()
        return _brutas[chave], _travas[chave]


def conectar(caminho: Path) -> Conexao:
    if SO_ADAPTADOR:   # sem réplica não há o que proteger: uma conexão por chamada, como no sqlite3
        import libsql
        caminho.parent.mkdir(parents=True, exist_ok=True)
        con = Conexao(libsql.connect(str(caminho), _check_same_thread=False), None)
    else:
        # uma réplica do Turso por arquivo e por processo: as requisições usam a mesma conexão, uma de cada vez
        bruta, trava = _bruta(caminho)
        if not trava.acquire(timeout=60):
            raise sqlite3.OperationalError("banco ocupado há mais de 60 s; feche e abra o CRM")
        con = Conexao(bruta, trava)
    try:
        con.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:
        pass   # alguns servidores ignoram/recusam PRAGMA; as chaves estrangeiras também são checadas no Turso
    return con


def sincronizar(caminho: Path) -> bool:
    """Puxa do Turso o que mudou. Sem internet: guarda o erro (aparece nos alertas) e segue com a réplica local."""
    if SO_ADAPTADOR:
        return True
    bruta, trava = _bruta(caminho)
    with trava:
        try:
            bruta.sync()
        except Exception as e:
            status["erro"] = str(e) or e.__class__.__name__
            return False
    status.update(ultima_sync=dt.datetime.now(), erro=None)
    return True


def iniciar_sync_periodico(caminho: Path) -> None:
    def laco():
        while True:
            sincronizar(caminho)
            threading.Event().wait(INTERVALO_SYNC)
    threading.Thread(target=laco, daemon=True, name="sync-turso").start()


# ---------- copiar dados de um arquivo SQLite para a conexão (subir e restaurar) ----------
def _ordem_tabelas(fks: dict) -> list:
    """{tabela: tabelas de que depende} -> pais antes dos filhos, para inserir sem violar chave estrangeira."""
    deps = {t: (d & set(fks)) - {t} for t, d in fks.items()}
    ordem = []
    while deps:
        prontas = sorted(t for t, d in deps.items() if d <= set(ordem)) or sorted(deps)   # ciclo: ordem alfabética
        for t in prontas:
            ordem.append(t)
            deps.pop(t)
    return ordem


def copiar_dados(origem: Path, con) -> dict:
    """Deixa as tabelas de `con` iguais às do arquivo `origem` (tabela que não existe no arquivo fica vazia).
    Devolve {tabela: linhas copiadas}."""
    src = sqlite3.connect(origem.as_uri() + "?mode=ro", uri=True)
    try:
        nomes = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        destino = [r[0] for r in con.execute(nomes).fetchall()]
        na_origem = {r[0] for r in src.execute(nomes)}
        ordem = _ordem_tabelas({t: {r[2] for r in con.execute(f"PRAGMA foreign_key_list({t})").fetchall()} for t in destino})
        contagem = {}
        with con:
            for t in reversed(ordem):   # filhos primeiro, para apagar sem violar chave estrangeira
                con.execute(f"DELETE FROM {t}")
            for t in ordem:
                if t not in na_origem:
                    continue
                cols_dest = {r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()}
                cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})") if r[1] in cols_dest]
                lista = ", ".join(cols)
                linhas = src.execute(f"SELECT {lista} FROM {t}").fetchall()
                if linhas:
                    con.executemany(f"INSERT INTO {t} ({lista}) VALUES ({', '.join('?' * len(cols))})", linhas)
                contagem[t] = len(linhas)
        return contagem
    finally:
        src.close()
