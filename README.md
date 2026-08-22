# Vinyl Collection

Flask + SQLAlchemy (SQLite by default) app for tracking a vinyl record collection.

## Rodando localmente

```bash
pip install -r requirements.txt
python app.py
```

Para popular o banco local com dados reais (backup exportado via `/api/export`), coloque o CSV como `vinyl_collection.csv` na raiz do projeto (arquivo gitignored, nunca commitado) e rode:

```bash
python seed_db.py
```

## Deploy no Railway

1. Conecte este repositório a um projeto no Railway.
2. Em **Variables**, defina:
   - `SECRET_KEY` — string aleatória para assinar a sessão.
   - `EDIT_PASSWORD` — senha para habilitar edição/import.
   - `DATA_DIR` — `/data`
   - `ANTHROPIC_API_KEY` — chave da API da Anthropic (console.anthropic.com).
     Não é a assinatura do Claude.ai; é cobrança separada por uso. Sem ela, o
     scan por foto fica desabilitado.
   - `MUSICBRAINZ_CONTACT` — e-mail de contato enviado no `User-Agent` para a
     MusicBrainz (obrigatório pela API deles).
   - `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — de um app registrado em
     developer.spotify.com. Sem eles, apenas o colar link do Spotify fica
     desabilitado.
3. Em **Settings → Volumes**, crie um volume e monte-o em `/data`. Sem isso, o banco SQLite vive no filesystem efêmero do Railway e é apagado a cada deploy.
4. O Railway detecta `railway.toml`/`Procfile` automaticamente (Nixpacks + gunicorn).

Com o volume montado em `/data` e `DATA_DIR=/data`, o banco (`/data/vinyl.db`) persiste entre deploys e restarts — não é mais necessário exportar/importar CSV como backup manual antes de cada deploy. Os endpoints `/api/export` e `/api/import` continuam disponíveis para backups manuais opcionais.
