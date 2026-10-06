# -*- coding: utf-8 -*-
"""Videos das resenhas: texto integral lido em duas vozes (cada paragrafo
alterna FRANCISCA / THALITA), com as mesmas vozes, velocidade e pausas das
videoaulas do TRT-8. Um slide por paragrafo: a secao, com o paragrafo atual
em destaque. Publica no release "resenhas" (no GitHub Actions).

    python -m estudio.render                    # os livros desta PARTE ainda nao publicados
    python -m estudio.render --livro 12 --local # so um, sem publicar (deixa em saida/)
    python -m estudio.render --livro 12 --local --secoes 2   # teste curto
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave

from . import slides as sl
from . import tts

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "saida")
TAG = "resenhas"

# as mesmas pausas das aulas do TRT-8
PAUSA_FRASE = 1.3        # depois de cada frase
PAUSA_PERGUNTA = 1.6     # depois de frase com "?"
PAUSA_FALA = 2.0         # fim do paragrafo (troca de voz)
PAUSA_SLIDE = 3.3        # fim da secao
CAPA_S = 4.0
FIM_S = 5.0
VOZES = ("FRANCISCA", "THALITA")

CADEIA_VOLUME = ("dynaudnorm=f=200:g=15:p=0.95:m=30:t=0.001,"
                 "acompressor=threshold=-22dB:ratio=4:attack=2:release=80:makeup=6,"
                 "alimiter=limit=0.60:attack=1:release=40:level=0")

PARTE = int(os.environ.get("PARTE", "0"))
PARTES = int(os.environ.get("PARTES", "1"))

# abreviaturas que a voz leria errado (ou que partiriam a frase no ponto)
ABREV = [
    (r"\bpp\.\s*(?=\d)", "páginas "), (r"\bPp\.\s*(?=\d)", "Páginas "),
    (r"\bp\.\s*(?=\d)", "página "),
    (r"\bcaps\.\s*", "capítulos "), (r"\bCaps\.\s*", "Capítulos "),
    (r"\bcap\.\s*", "capítulo "), (r"\bCap\.\s*", "Capítulo "),
    (r"\bvol\.\s*", "volume "), (r"\bVol\.\s*", "Volume "),
    (r"\bv\.\s*(?=\d)", "volume "), (r"\bn\.\s*(?=\d)", "número "),
    (r"\bed\.\s*", "edição "), (r"\bJr\.", "Júnior"), (r"\bart\.\s*", "artigo "),
    (r"\bjan\.(?=\s*[/\d])", "janeiro"), (r"\bfev\.(?=\s*[/\d])", "fevereiro"),
    (r"\bmar\.(?=\s*[/\d])", "março"), (r"\babr\.(?=\s*[/\d])", "abril"),
    (r"\bmai\.(?=\s*[/\d])", "maio"), (r"\bjun\.(?=\s*[/\d])", "junho"),
    (r"\bjul\.(?=\s*[/\d])", "julho"), (r"\bago\.(?=\s*[/\d])", "agosto"),
    (r"\bset\.(?=\s*[/\d])", "setembro"), (r"\bout\.(?=\s*[/\d])", "outubro"),
    (r"\bnov\.(?=\s*[/\d])", "novembro"), (r"\bdez\.(?=\s*[/\d])", "dezembro"),
    (r"\bet al\.", "e outros"), (r"\bop\. cit\.", "obra citada"),
    (r"\bSr\.", "Senhor"), (r"\bSra\.", "Senhora"), (r"\bDr\.", "Doutor"), (r"\bDra\.", "Doutora"),
    (r"\bséc\.\s*", "século "), (r"\bp\. ex\.", "por exemplo"),
]


def falado(t):
    """Texto como a voz deve ler."""
    t = re.sub(r"\(?<?https?://[^\s)>]+>?\)?", "", t)       # endereco de site nao se le
    t = re.sub(r"\bwww\.\S+", "", t)
    t = re.sub(r"[*_#`]+", "", t)
    t = t.replace("[", "").replace("]", "").replace("§", "parágrafo").replace("&", "e")
    for a, b in ABREV:
        t = re.sub(a, b, t)
    return re.sub(r"\s+", " ", t).strip()


def frases(texto):
    out = []
    for f in re.split(r"(?<=[.!?…])\s+(?=[\"“'(«A-ZÁÉÍÓÚÂÊÔÃÕÀÇ0-9])", texto):
        f = f.strip()
        if not re.search(r"\w", f):
            continue
        while len(f) > 700:                  # frase enorme: parte no ponto e virgula
            k = f.rfind("; ", 0, 700)
            if k < 200:
                break
            out.append(f[:k + 1])
            f = f[k + 2:]
        out.append(f)
    return out


def topico(paragrafo):
    """Primeira frase do paragrafo, para o slide."""
    t = re.sub(r"[*_#`]+", "", paragrafo)
    p = re.split(r"(?<=[.!?…])\s+(?=[\"“(A-ZÁÉÍÓÚÂÊÔÃÕÀÇ])", t, maxsplit=1)[0]
    return p if len(p) <= 150 else p[:147].rsplit(" ", 1)[0] + "…"


def sem_parenteses(t):
    return re.sub(r"\s*\([^)]*\)", "", t).strip(" .")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def ff(*args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + list(args), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("ffmpeg: " + r.stderr[-600:])


def gh(*args, ok=False):
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if r.returncode and not ok:
        raise RuntimeError("gh %s: %s" % (args[0], r.stderr[-400:]))
    return r


def livros():
    pasta = os.path.join(RAIZ, "textos")
    return [json.load(open(os.path.join(pasta, n), encoding="utf-8")) for n in sorted(os.listdir(pasta))]


def da_parte(todos):
    """Divide os livros entre as maquinas pelo tamanho (maior primeiro)."""
    carga = [0] * PARTES
    dono = {}
    for l in sorted(todos, key=lambda x: -x["palavras"]):
        i = carga.index(min(carga))
        carga[i] += l["palavras"]
        dono[l["numero"]] = i
    return [l for l in todos if dono[l["numero"]] == PARTE]


def roteiro(livro, max_secoes=None):
    """[(secao_idx, paragrafo_idx, voz, frase_falada, pausa_depois)]"""
    secoes = livro["secoes"][:max_secoes] if max_secoes else livro["secoes"]
    itens = []
    abertura = "Resenha de %s" % sem_parenteses(livro["titulo"])
    if livro.get("autor"):
        abertura += ", de %s" % sem_parenteses(livro["autor"])
    itens.append((-1, 0, "FRANCISCA", falado(abertura) + ".", PAUSA_SLIDE))
    n_par = 0
    parte_ant = None
    for si, s in enumerate(secoes):
        for pi, par in enumerate(s["paragrafos"]):
            voz = VOZES[n_par % 2]
            n_par += 1
            fs = []
            if pi == 0:
                if s["parte"] and s["parte"] != parte_ant and s["parte"] != s["titulo"]:
                    fs.append(falado(s["parte"]).rstrip(".:") + ".")
                fs.append(falado(s["titulo"]).rstrip(".:") + ".")
                parte_ant = s["parte"]
            fs += frases(falado(par))
            for k, f in enumerate(fs):
                if k == len(fs) - 1:
                    p = PAUSA_SLIDE if pi == len(s["paragrafos"]) - 1 else PAUSA_FALA
                else:
                    p = PAUSA_PERGUNTA if f.endswith("?") else PAUSA_FRASE
                itens.append((si, pi, voz, f, p))
    return secoes, itens


def _srt(eventos, destino):
    def hms(s):
        return ("%02d:%02d:%06.3f" % (s // 3600, (s % 3600) // 60, s % 60)).replace(".", ",")
    with open(destino, "w", encoding="utf-8") as f:
        for n, (ini, fim, texto) in enumerate(eventos, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (n, hms(ini), hms(fim), texto))


def montar(livro, todos, destino_dir, max_secoes=None):
    base = livro["arquivo"]
    tmp = os.path.join(SAIDA, "_tmp", base)
    cache = os.path.join(tmp, "voz")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(destino_dir, exist_ok=True)

    secoes, itens = roteiro(livro, max_secoes)
    log("%s: %d secoes, %d frases -> voz" % (base, len(secoes), len(itens)))
    wavs = tts.sintetizar([(v, f) for _, _, v, f, _ in itens], cache)

    prox = next((l for l in todos if l["numero"] > livro["numero"]), None)
    capa = sl.capa(os.path.join(tmp, "capa.png"), livro, len(todos))
    fim = sl.capa(os.path.join(tmp, "fim.png"), livro, len(todos), final=True, proximo=prox)
    topicos = [[topico(p) for p in s["paragrafos"]] for s in secoes]

    bruto = os.path.join(tmp, "bruto.wav")
    out = wave.open(bruto, "wb")
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(tts.TAXA)
    out.writeframes(tts.silencio(CAPA_S))
    linha = [[capa, CAPA_S]]
    eventos, t = [], CAPA_S
    chave_ant = None
    log("%s: montando o audio" % base)
    for (si, pi, voz, fr, pausa), w in zip(itens, wavs):
        audio = tts.ler_frase(w, fr)
        dur = len(audio) / 2 / tts.TAXA
        out.writeframes(audio)
        out.writeframes(tts.silencio(pausa))
        if si < 0:
            linha[-1][1] += dur + pausa
        else:
            if (si, pi) != chave_ant:
                img = sl.leitura(os.path.join(tmp, "s%03d_%02d.png" % (si, pi)), livro, secoes[si],
                                 topicos[si], pi, si + 1, len(secoes))
                linha.append([img, 0.0])
                chave_ant = (si, pi)
            linha[-1][1] += dur + pausa
        eventos.append((t, t + dur, fr))
        t += dur + pausa
    out.writeframes(tts.silencio(FIM_S))
    out.close()
    linha.append([fim, FIM_S])
    shutil.rmtree(cache, ignore_errors=True)

    log("%s: audio (%.1f min) -> volume e AAC" % (base, (t + FIM_S) / 60))
    m4a = os.path.join(tmp, "audio.m4a")
    ff("-i", bruto, "-af", CADEIA_VOLUME, "-ar", "24000", "-ac", "1", "-c:a", "aac", "-b:a", "40k", m4a)
    os.remove(bruto)

    lista = os.path.join(tmp, "imagens.txt")
    with open(lista, "w", encoding="utf-8") as f:
        for img, dur in linha:
            f.write("file '%s'\nduration %.4f\n" % (os.path.abspath(img).replace("\\", "/"), dur))
        f.write("file '%s'\n" % os.path.abspath(linha[-1][0]).replace("\\", "/"))
    mp4 = os.path.join(destino_dir, base + ".mp4")
    srt = os.path.join(destino_dir, base + ".srt")
    log("%s: video" % base)
    ff("-f", "concat", "-safe", "0", "-i", lista, "-i", m4a,
       "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "30",
       "-r", "2", "-g", "600", "-pix_fmt", "yuv420p",
       "-c:a", "copy", "-movflags", "+faststart", "-shortest", mp4)
    _srt(eventos, srt)
    shutil.rmtree(tmp, ignore_errors=True)
    return [mp4, srt], (t + FIM_S) / 60


def publicados():
    r = gh("release", "view", TAG, "--json", "assets", ok=True)
    if r.returncode:
        gh("release", "create", TAG, "--title", "Resenhas em vídeo",       # outra maquina pode ter criado
           "--notes", "Gerando... os vídeos aparecem aqui conforme ficam prontos.", ok=True)
        return set()
    return {a["name"] for a in json.loads(r.stdout)["assets"] if a["size"] > 0}


def notas(todos):
    nomes = publicados()
    feitos = [l for l in todos if l["arquivo"] + ".mp4" in nomes]
    linhas = ["**%d de %d livros prontos**\n" % (len(feitos), len(todos)),
              "Cada livro tem o vídeo (.mp4) e a legenda (.srt).\n"]
    for l in feitos:
        linhas.append("- %03d · %s" % (l["numero"], l["titulo"].replace("|", "/")))
    arq = os.path.join(SAIDA, "notas.md")
    os.makedirs(SAIDA, exist_ok=True)
    with open(arq, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    gh("release", "edit", TAG, "--notes-file", arq)
    log("%d de %d livros publicados" % (len(feitos), len(todos)))
    return len(feitos) == len(todos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--livro", type=int)
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--secoes", type=int, help="so as N primeiras secoes (teste)")
    ap.add_argument("--max-minutos", type=float, default=320)
    ap.add_argument("--notas", action="store_true", help="so atualiza o texto do release")
    a = ap.parse_args()
    inicio = time.time()
    todos = livros()

    if a.notas:
        completo = notas(todos)
        print("COMPLETO" if completo else "PENDENTE")
        return

    if a.livro:
        fila = [l for l in todos if l["numero"] == a.livro]
    else:
        fila = da_parte(todos)
    nomes = set() if a.local else publicados()
    falhas = 0
    for livro in fila:
        if not a.livro and livro["arquivo"] + ".mp4" in nomes:
            continue
        if (time.time() - inicio) / 60 > a.max_minutos:
            log("tempo esgotado; o resto fica para a próxima execução")
            break
        try:
            arquivos, minutos = montar(livro, todos, SAIDA, a.secoes)
        except Exception as e:
            log("FALHOU %s: %s" % (livro["arquivo"], e))
            falhas += 1
            continue
        if not a.local:
            gh("release", "upload", TAG, "--clobber", *arquivos)
            for x in arquivos:
                os.remove(x)
        log("PRONTO %s (%.1f min de vídeo)" % (livro["arquivo"], minutos))
    if falhas:
        sys.exit(1)


if __name__ == "__main__":
    main()
