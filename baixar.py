# -*- coding: utf-8 -*-
"""Baixa do GitHub (release "resenhas") todos os videos e legendas prontos para
a pasta indicada, conferindo o tamanho de cada arquivo. Pode rodar de novo a
qualquer momento: o que ja foi baixado inteiro e pulado.

    python baixar.py "C:/Users/elhoa/Downloads/RESENHAS LIVROS FORMATADAS/VIDEOS"
"""
import json
import os
import shutil
import subprocess
import sys

GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
REPO = "dirprivadoleonardobatista-ai/resenhas-livros"


def main():
    destino = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\elhoa\Downloads\RESENHAS LIVROS FORMATADAS\VIDEOS"
    os.makedirs(destino, exist_ok=True)
    r = subprocess.run([GH, "release", "view", "resenhas", "-R", REPO, "--json", "assets"], capture_output=True,
                       text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
    if r.returncode:
        sys.exit("Não consegui ler o release: " + r.stderr)
    assets = sorted((a["name"], a["size"]) for a in json.loads(r.stdout)["assets"]
                    if a["name"].endswith((".mp4", ".srt")))
    ok, falhas = 0, []
    for n, tam in assets:
        alvo = os.path.join(destino, n)
        if os.path.exists(alvo) and os.path.getsize(alvo) == tam:
            ok += 1
            continue
        livre = shutil.disk_usage(destino).free
        if livre < tam + 500 * 1024 * 1024:
            print("PAROU: disco quase cheio (%.1f GB livres)." % (livre / 1e9))
            break
        for tentativa in range(3):
            p = subprocess.run([GH, "release", "download", "resenhas", "-R", REPO, "-p", n, "-D", destino,
                                "--clobber"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if os.path.exists(alvo) and os.path.getsize(alvo) == tam:
                ok += 1
                break
        else:
            falhas.append((n, (p.stderr or "")[:150]))
        print("%d/%d %s" % (ok, len(assets), n), flush=True)
    print("BAIXADOS: %d de %d arquivos" % (ok, len(assets)))
    for n, e in falhas:
        print("FALHOU", n, e)


if __name__ == "__main__":
    main()
