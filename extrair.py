# -*- coding: utf-8 -*-
"""Le os .docx das resenhas e grava textos/NNN.json (titulo, autor, partes).
Roda so no computador local (os .docx nao vao para o repositorio).

    python extrair.py "C:/Users/elhoa/Downloads/RESENHAS LIVROS FORMATADAS"
"""
import glob
import json
import os
import re
import sys

import docx

META = re.compile(r"^(Compêndio analítico|Estudo gerado|Texto gerado)", re.I)


def extrair(arq):
    d = docx.Document(arq)
    livro = {"arquivo": os.path.splitext(os.path.basename(arq))[0], "titulo": "", "autor": "",
             "aviso": "", "secoes": []}
    h1 = ""
    atual = None
    for p in d.paragraphs:
        t = re.sub(r"\s+", " ", p.text).strip()
        if not t:
            continue
        estilo = p.style.name
        if estilo == "Title":
            livro["titulo"] = t
        elif estilo == "Heading 1":
            h1, atual = t, None
        elif estilo.startswith("Heading"):
            atual = {"parte": h1, "titulo": t, "paragrafos": []}
            livro["secoes"].append(atual)
        elif atual is None and not livro["secoes"] and not h1:
            if META.match(t):
                if t.lower().startswith("texto gerado"):
                    livro["aviso"] = t
            elif not livro["autor"] and len(t) < 120:
                livro["autor"] = t
            else:
                atual = {"parte": "", "titulo": livro["titulo"], "paragrafos": [t]}
                livro["secoes"].append(atual)
        else:
            if atual is None:
                atual = {"parte": h1, "titulo": h1 or livro["titulo"], "paragrafos": []}
                livro["secoes"].append(atual)
            atual["paragrafos"].append(t)
    livro["secoes"] = [s for s in livro["secoes"] if s["paragrafos"]]
    return livro


def main():
    origem = sys.argv[1]
    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textos")
    os.makedirs(destino, exist_ok=True)
    total = 0
    for arq in sorted(glob.glob(os.path.join(origem, "[0-9][0-9][0-9]-*.docx"))):
        if os.path.basename(arq).startswith("000"):
            continue
        livro = extrair(arq)
        n = int(os.path.basename(arq)[:3])
        livro["numero"] = n
        palavras = sum(len(p.split()) for s in livro["secoes"] for p in s["paragrafos"])
        livro["palavras"] = palavras
        total += palavras
        with open(os.path.join(destino, "%03d.json" % n), "w", encoding="utf-8") as f:
            json.dump(livro, f, ensure_ascii=False, indent=0)
    print("livros:", len(os.listdir(destino)), "palavras:", total)


if __name__ == "__main__":
    main()
