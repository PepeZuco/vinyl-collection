# Vinyl Collection

Flask + SQLAlchemy (SQLite by default) app for tracking a vinyl record collection.

## Rodando localmente

```bash
pip install -r requirements.txt
python app.py
```

## Deploy no Railway

1. Conecte este repositório a um projeto no Railway.
2. Em **Variables**, defina:
   - `SECRET_KEY` — string aleatória para assinar a sessão.
   - `EDIT_PASSWORD` — senha para habilitar edição/import.
   - `DATA_DIR` — `/data`
3. Em **Settings → Volumes**, crie um volume e monte-o em `/data`. Sem isso, o banco SQLite vive no filesystem efêmero do Railway e é apagado a cada deploy.
4. O Railway detecta `railway.toml`/`Procfile` automaticamente (Nixpacks + gunicorn).

Com o volume montado em `/data` e `DATA_DIR=/data`, o banco (`/data/vinyl.db`) persiste entre deploys e restarts — não é mais necessário exportar/importar CSV como backup manual antes de cada deploy. Os endpoints `/api/export` e `/api/import` continuam disponíveis para backups manuais opcionais.
