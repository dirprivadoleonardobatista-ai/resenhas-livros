# Resenhas em vídeo

As 86 resenhas do compêndio (`textos/NNN.json`, extraídas dos .docx por
`extrair.py`) lidas na íntegra em duas vozes, Francisca e Thalita, que alternam
a cada parágrafo. Vozes, velocidade e pausas são as mesmas das videoaulas do
TRT-8. Há um slide por parágrafo, com a seção na tela e o parágrafo lido em
destaque.

O GitHub Actions (`.github/workflows/resenhas.yml`) gera os vídeos e publica
no release `resenhas`.

Para baixar tudo para o computador:

    python baixar.py "C:/Users/elhoa/Downloads/RESENHAS LIVROS FORMATADAS/VIDEOS"
