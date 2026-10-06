# -*- coding: utf-8 -*-
"""Slides em PNG (Pillow): capa, slide de leitura (secao com o paragrafo atual
em destaque) e tela final."""
import os
import re

from PIL import Image, ImageDraw, ImageFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1280, 720

FUNDO = "#F5F7FB"
AZUL_ESCURO = "#13294B"
AZUL = "#2E86C1"
TEXTO = "#1E2533"
CINZA = "#8A94A6"
CINZA_CLARO = "#B4BCCB"
RODAPE = "Resenhas · Compêndio analítico"

_fontes = {}


def fonte(tam, peso="Regular"):
    k = (tam, peso)
    if k not in _fontes:
        _fontes[k] = ImageFont.truetype(os.path.join(RAIZ, "fontes", "Inter-%s.ttf" % peso), tam)
    return _fontes[k]


def quebrar(d, texto, f, largura):
    linhas, atual = [], ""
    for p in texto.split():
        teste = (atual + " " + p).strip()
        if d.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def limpo(titulo):
    """Titulo sem as notas entre parenteses ("(em português)", "(a lista traz...)")."""
    return re.sub(r"\s*\([^)]*\)", "", titulo).strip(" .") or titulo


def _cortar(d, txt, f, largura):
    if d.textlength(txt, font=f) <= largura:
        return txt
    while d.textlength(txt + "…", font=f) > largura and len(txt) > 10:
        txt = txt[:-1]
    return txt.rstrip(" —-·,;:") + "…"


def _cabecalho(d, livro):
    d.rectangle([0, 0, W, 62], fill=AZUL_ESCURO)
    marca = "LIVRO %02d" % livro["numero"]
    fm = fonte(19, "Bold")
    lm = d.textlength(marca, font=fm)
    d.text((40, 20), _cortar(d, limpo(livro["titulo"]).upper(), fonte(19, "SemiBold"), W - 120 - lm),
           font=fonte(19, "SemiBold"), fill="white")
    d.text((W - 40 - lm, 20), marca, font=fm, fill="#9CC9EA")


def _rodape(d, num, total):
    f = fonte(14)
    d.text((40, H - 34), RODAPE, font=f, fill=CINZA)
    if total:
        m = "seção %d / %d" % (num, total)
        d.text((W - 40 - d.textlength(m, font=f), H - 34), m, font=f, fill=CINZA)


def leitura(destino, livro, secao, topicos, atual, num, total):
    """Titulo da secao e um topico por paragrafo; o paragrafo lido fica em
    destaque e os demais em cinza. Se nao couberem todos, mostra uma janela
    em volta do atual."""
    img = Image.new("RGB", (W, H), FUNDO)
    d = ImageDraw.Draw(img)
    _cabecalho(d, livro)
    x, larg = 60, W - 120
    y = 84
    if secao["parte"] and secao["parte"] != secao["titulo"]:
        d.text((x, y), _cortar(d, secao["parte"].upper(), fonte(17, "Bold"), larg), font=fonte(17, "Bold"), fill=AZUL)
        y += 30
    ft = fonte(34, "Bold")
    for l in quebrar(d, secao["titulo"], ft, larg)[:2]:
        d.text((x, y), l, font=ft, fill=AZUL_ESCURO)
        y += int(ft.size * 1.22)
    y += 8
    d.rectangle([x, y, x + 110, y + 5], fill=AZUL)
    y += 28

    f, fb = fonte(24), fonte(24, "SemiBold")
    passo = int(f.size * 1.32)
    blocos = [quebrar(d, t, fb if i == atual else f, larg - 44)[:3] for i, t in enumerate(topicos)]
    limite = H - 56
    ini = 0
    while True:                         # menor janela que contem o atual e cabe
        fim = ini
        alt = 0
        while fim < len(blocos) and y + alt + len(blocos[fim]) * passo <= limite:
            alt += len(blocos[fim]) * passo + int(f.size * 0.7)
            fim += 1
        if atual < fim or ini >= atual:
            break
        ini += 1
    for i in range(ini, fim):
        cor = TEXTO if i == atual else CINZA_CLARO
        cy = y + int(f.size * 0.42)
        d.rounded_rectangle([x + 2, cy, x + 14, cy + 12], radius=3, fill=AZUL if i == atual else CINZA_CLARO)
        for l in blocos[i]:
            d.text((x + 36, y), l, font=fb if i == atual else f, fill=cor)
            y += passo
        y += int(f.size * 0.7)
    _rodape(d, num, total)
    img.save(destino, optimize=True)
    return destino


def capa(destino, livro, total_livros, final=False, proximo=None):
    img = Image.new("RGB", (W, H), AZUL_ESCURO)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 10, W, H], fill=AZUL)
    x, larg = 70, W - 140
    d.text((x, 70), ("FIM DO LIVRO %02d" if final else "LIVRO %02d  ·  de %d") % (
        (livro["numero"],) if final else (livro["numero"], total_livros)), font=fonte(22, "Bold"), fill="#9CC9EA")
    y = 130
    ft = fonte(44 if len(limpo(livro["titulo"])) < 90 else 36, "Bold")
    for l in quebrar(d, limpo(livro["titulo"]), ft, larg)[:4]:
        d.text((x, y), l, font=ft, fill="white")
        y += int(ft.size * 1.2)
    y += 20
    if livro.get("autor"):
        for l in quebrar(d, livro["autor"], fonte(28), larg)[:2]:
            d.text((x, y), l, font=fonte(28), fill="#C9D6EA")
            y += 38
    if final and proximo:
        y += 40
        d.text((x, y), "A SEGUIR", font=fonte(18, "Bold"), fill="#9CC9EA")
        y += 32
        for l in quebrar(d, "Livro %02d — %s" % (proximo["numero"], limpo(proximo["titulo"])), fonte(26), larg)[:2]:
            d.text((x, y), l, font=fonte(26), fill="white")
            y += 36
    elif livro.get("aviso"):
        y = max(y + 30, H - 150)
        for l in quebrar(d, livro["aviso"], fonte(18), larg)[:3]:
            d.text((x, y), l, font=fonte(18), fill="#9CC9EA")
            y += 26
    d.text((x, H - 50), RODAPE, font=fonte(16), fill="#9CC9EA")
    img.save(destino, optimize=True)
    return destino
