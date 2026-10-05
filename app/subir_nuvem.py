"""Envia o crm.db local para o banco na nuvem (Turso). Rodar uma vez, com o CRM fechado:

    .venv\\Scripts\\python.exe -m app.subir_nuvem

Precisa de TURSO_DATABASE_URL e TURSO_AUTH_TOKEN no .env. O crm.db local não é alterado.
Se o Turso já tiver alunos cadastrados, recusa (para não apagar nada); --substituir força.
"""
import argparse
import sqlite3
import sys

from . import db, nuvem


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Envia o crm.db local para o Turso.")
    ap.add_argument("--substituir", action="store_true", help="apaga o que já estiver no Turso antes de enviar")
    args = ap.parse_args(argv)
    if not (nuvem.preenchido(nuvem.URL) and nuvem.preenchido(nuvem.TOKEN)):
        print("O .env não foi encontrado ou ainda está com os textos de exemplo.\n"
              "Abra com: notepad .env  e troque a URL e o token pelos do Turso (veja o README).")
        return 1
    if not db.DB_LOCAL.exists():
        print(f"Banco local não encontrado: {db.DB_LOCAL}")
        return 1
    print("Conectando ao Turso...")
    if not nuvem.sincronizar(db.DB_PATH):
        print(f"Não consegui conectar: {nuvem.status['erro']}\nConfira a internet, a URL e o token no .env.")
        return 1
    print("Backup do banco local:", db.fazer_backup("antes-nuvem", db.DB_LOCAL))
    db.iniciar_banco()   # cria as tabelas no Turso, se for a primeira vez
    con = db.conectar()
    try:
        ja_tem = con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
        if ja_tem and not args.substituir:
            print(f"O Turso já tem {ja_tem} cliente(s). Nada foi enviado. Para substituir tudo: --substituir")
            return 1
        print("Enviando (pode levar 1 a 2 minutos)...")
        contagem = nuvem.copiar_dados(db.DB_LOCAL, con)
        local = sqlite3.connect(db.DB_LOCAL.as_uri() + "?mode=ro", uri=True)
        erros = []
        for t, n in contagem.items():
            remoto = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if remoto != n or local.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] != n:
                erros.append(t)
            if n:
                print(f"  {t:28s} {n:6d}")
        local.close()
    finally:
        con.close()
    nuvem.sincronizar(db.DB_PATH)
    if erros:
        print("ATENÇÃO: contagem diferente em:", ", ".join(erros))
        return 1
    print(f"\nPRONTO: {sum(contagem.values())} linhas no Turso. Abra o CRM normalmente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
