# -*- coding: utf-8 -*-
"""Narracao com edge-tts (gratuito). Cada frase vira um WAV PCM, para que a
linha do tempo do video seja exata (MP3 colado acumula atraso).

Pausas na pontuacao: a voz sintetica quase nao para na virgula nem nos
dois-pontos. O edge-tts informa quando cada palavra comeca e termina; depois
de cada palavra seguida de virgula, dois-pontos, ponto e virgula ou travessao,
insere-se um silencio no ponto mais quieto entre as duas palavras. A
entonacao da frase fica intacta (nada e sintetizado em pedacos)."""
import array
import asyncio
import hashlib
import json
import os
import re
import subprocess
import wave

TAXA = 24000          # Hz, mono, 16 bits: o que o edge-tts entrega

# voz, tom, ritmo. Opcao E aprovada no teste: -7% e tom natural (voz lenta + tom
# grave fazia a voz engolir o final das palavras). Ritmo real medido abaixo, por
# minuto articulando (medido a 0%: Francisca 167, Thalita 176).
# A personagem THALITA usa a voz Seraphina: a voz Thalita (e as outras femininas
# multilingues, Ava e Vivienne) apaga a ultima vogal atona no fim da frase
# ("marco" sai "marc", queda de ~24 dB, sem a vogal); nenhum ritmo, tom ou
# pontuacao corrige. Francisca e Seraphina mantem a silaba final (~-12 dB).
VOZES_TTS = {
    "FRANCISCA": ("pt-BR-FranciscaNeural",             "+0Hz",  "-7%"),
    "THALITA":   ("de-DE-SeraphinaMultilingualNeural", "+0Hz",  "-7%"),
}

# silencio ACRESCENTADO depois da pontuacao (a voz ja faz de 0 a 0,3 s)
PAUSA_PONTUACAO = {",": 0.55, ";": 0.80, ":": 1.00, "—": 0.65, "–": 0.65}

PARALELO = int(os.environ.get("TTS_PARALELO", "6"))


def _chave(voz, texto):
    nome, tom, ritmo = VOZES_TTS[voz]
    return hashlib.sha1(("%s|%s|%s|%s" % (nome, tom, ritmo, texto)).encode("utf-8")).hexdigest()[:20]


async def _uma(sem, voz, texto, mp3):
    import edge_tts
    nome, tom, ritmo = VOZES_TTS[voz]
    async with sem:
        erro = None
        for tentativa in range(6):
            try:
                com = edge_tts.Communicate(texto, nome, rate=ritmo, pitch=tom, boundary="WordBoundary")
                audio, palavras = bytearray(), []
                async for ch in com.stream():
                    if ch["type"] == "audio":
                        audio += ch["data"]
                    elif ch["type"] == "WordBoundary":
                        palavras.append([ch["offset"] / 1e7, ch["duration"] / 1e7, ch["text"]])
                if len(audio) > 1500:
                    with open(mp3 + ".json", "w", encoding="utf-8") as f:
                        json.dump(palavras, f, ensure_ascii=False)
                    with open(mp3, "wb") as f:
                        f.write(audio)
                    return None
                erro = "audio vazio"
            except Exception as e:          # rede, 429, 503...
                erro = "%s: %s" % (type(e).__name__, str(e)[:120])
            await asyncio.sleep(2 + 4 * tentativa)
        return erro


def _wav(mp3, wav):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-ac", "1", "-ar", str(TAXA),
                    "-sample_fmt", "s16", wav], check=True)


def sintetizar(frases, cache):
    """frases = [(VOZ, texto)] -> [caminho_wav] na mesma ordem. Ao lado de
    cada .mp3 fica um .mp3.json com o tempo de cada palavra."""
    os.makedirs(cache, exist_ok=True)
    alvos = []
    for voz, texto in frases:
        base = os.path.join(cache, _chave(voz, texto))
        alvos.append((voz, texto, base + ".mp3", base + ".wav"))

    vistos, faltam = set(), []
    for v, t, m, w in alvos:
        if m not in vistos and not (os.path.exists(m) and os.path.exists(m + ".json")):
            faltam.append((v, t, m))
            vistos.add(m)

    async def tudo():
        sem = asyncio.Semaphore(PARALELO)
        return await asyncio.gather(*[_uma(sem, v, t, m) for v, t, m in faltam])

    if faltam:
        erros = [e for e in asyncio.run(tudo()) if e]
        if erros:
            raise RuntimeError("TTS falhou em %d frases (ex.: %s)" % (len(erros), erros[0]))

    from concurrent.futures import ThreadPoolExecutor
    pend = list({(m, w) for _, _, m, w in alvos if not os.path.exists(w)})
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        list(ex.map(lambda mw: _wav(*mw), pend))
    return [w for _, _, _, w in alvos]


def _pontos_de_pausa(texto, palavras):
    """[(instante_entre_palavras_s, pausa_s)] para cada palavra seguida de pontuacao."""
    saida, cursor = [], 0
    for i, (ini, dur, w) in enumerate(palavras):
        k = texto.find(w, cursor)
        if k < 0:
            continue
        cursor = k + len(w)
        m = re.match(r"\s*([,;:—–])", texto[cursor:])
        if m and i + 1 < len(palavras):
            fim = ini + dur
            prox = palavras[i + 1][0]
            saida.append(((fim + prox) / 2, fim, prox, PAUSA_PONTUACAO[m.group(1)]))
    return saida


def _ponto_quieto(a, fim_palavra, inicio_proxima, limiar=60, minimo_ms=40):
    """Onde inserir a pausa da pontuacao: no FIM do maior silencio real (pico
    abaixo de -55 dBFS por pelo menos 40 ms) entre as duas palavras, logo antes
    da proxima comecar. Assim todo o final da palavra anterior soa. Se a voz
    emenda as palavras sem silencio real, devolve None e nao se corta nada."""
    j = int(0.005 * TAXA)
    ini = max(0, int((fim_palavra - 0.02) * TAXA))
    fim = min(len(a) - j, int((inicio_proxima + 0.02) * TAXA))
    melhor, run_ini, run = (0, None), None, 0
    for s_ in range(ini, fim, j):
        if max(abs(x) for x in a[s_:s_ + j]) < limiar:
            if run == 0:
                run_ini = s_
            run += 1
            if run > melhor[0]:
                melhor = (run, run_ini)
        else:
            run = 0
    if melhor[0] * 5 < minimo_ms:
        return None
    return melhor[1] + melhor[0] * j - j // 2


def _rampa(a, ini, n, subindo):
    """Fade linear em a[ini:ini+n] (evita o estalo de corte seco)."""
    n = max(0, min(n, len(a) - ini))
    for i in range(n):
        g = (i / float(n)) if subindo else (1.0 - i / float(n))
        a[ini + i] = int(a[ini + i] * g)


def _realcar_finais(a, texto, palavras, alvo_db=-3.0, max_db=12.0, minimo_db=4.0):
    """A voz sussurra a ultima silaba atona de palavras longas antes de pausa
    (naturaliza-DO cai ate 10-15 dB). Sobe so esse trecho (ultimos ~30% da
    palavra + a cauda) ate ficar alvo_db abaixo do corpo da palavra, com rampas
    de 30 ms. Palavras que ja soam bem nao sao tocadas."""
    import math
    cursor = 0
    for i, (ini, dur, w) in enumerate(palavras):
        k = texto.find(w, cursor)
        if k < 0:
            continue
        cursor = k + len(w)
        antes_de_pausa = i == len(palavras) - 1 or re.match(r"\s*[,;:.!?…—–]", texto[cursor:])
        if not antes_de_pausa or len(w) < 6 or dur < 0.30:
            continue
        p0 = int(ini * TAXA)
        p_fim_silaba = int((ini + dur * 0.70) * TAXA)
        limite = int(palavras[i + 1][0] * TAXA) if i + 1 < len(palavras) else len(a)
        p1 = min(len(a), limite, int((ini + dur + 0.08) * TAXA))
        if p1 - p_fim_silaba < int(0.05 * TAXA):
            continue
        corpo = a[p0:p_fim_silaba]
        fim = a[p_fim_silaba:p1]
        rms = lambda seg: math.sqrt(sum(x * x for x in seg) / max(1, len(seg))) + 1e-9
        queda = 20 * math.log10(rms(fim) / rms(corpo))
        if queda > -minimo_db:
            continue
        ganho = min(max_db, alvo_db - queda)
        g = 10 ** (ganho / 20.0)
        rampa = int(0.03 * TAXA)
        n = p1 - p_fim_silaba
        for j in range(n):
            subida = min(1.0, j / rampa)
            descida = min(1.0, (n - j) / (rampa * 0.7))
            fator = 1.0 + (g - 1.0) * min(subida, descida)
            v = int(a[p_fim_silaba + j] * fator)
            a[p_fim_silaba + j] = max(-32767, min(32767, v))


def ler_frase(wav, texto, margem=0.05, margem_fim=0.15, limiar=120):
    """PCM da frase com as pausas da pontuacao e sem o silencio que a voz poe
    no comeco e no fim: cada pausa da aula tem o tamanho programado."""
    with wave.open(wav, "rb") as w:
        assert w.getframerate() == TAXA and w.getnchannels() == 1 and w.getsampwidth() == 2
        a = array.array("h", w.readframes(w.getnframes()))

    meta = wav[:-4] + ".mp3.json"
    if os.path.exists(meta):
        with open(meta, encoding="utf-8") as f:
            palavras = json.load(f)
        if texto:
            _realcar_finais(a, texto, palavras)
        cortes = [(_ponto_quieto(a, lo, hi), p) for c, lo, hi, p in _pontos_de_pausa(texto, palavras)]
        cortes = [(pos, p) for pos, p in cortes if pos is not None]
        if cortes:
            r_sai, r_entra = int(0.005 * TAXA), int(0.005 * TAXA)   # o corte ja cai em silencio
            novo, ant = array.array("h"), 0
            for pos, p in sorted(cortes):
                pedaco = a[ant:pos]
                if ant:
                    _rampa(pedaco, 0, r_entra, True)
                _rampa(pedaco, max(0, len(pedaco) - r_sai), r_sai, False)
                novo.extend(pedaco)
                novo.extend(array.array("h", bytes(2 * int(p * TAXA))))
                ant = pos
            pedaco = a[ant:]
            _rampa(pedaco, 0, r_entra, True)
            novo.extend(pedaco)
            a = novo

    ini = next((i for i, v in enumerate(a) if abs(v) > limiar), 0)
    fim = next((i for i in range(len(a) - 1, -1, -1) if abs(a[i]) > limiar), len(a) - 1)
    a = a[max(0, ini - int(margem * TAXA)):min(len(a), fim + 1 + int(margem_fim * TAXA))]
    _rampa(a, 0, int(0.010 * TAXA), True)
    _rampa(a, len(a) - int(0.040 * TAXA), int(0.040 * TAXA), False)
    return a.tobytes()


def bipe():
    """Dois toques curtos e suaves (fim do tempo de leitura)."""
    import math
    a = array.array("h")
    for k in range(2):
        n = int(0.18 * TAXA)
        for i in range(n):
            env = min(1.0, i / 600.0, (n - i) / 600.0)
            a.append(int(9000 * env * math.sin(2 * math.pi * 880 * i / TAXA)))
        a.extend(array.array("h", bytes(2 * int(0.12 * TAXA))))
    return a.tobytes()


def silencio(segundos):
    return b"\x00\x00" * int(round(segundos * TAXA))


def gravar_wav(pcm, destino):
    with wave.open(destino, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(pcm)
