# Vinyl Collection

Flask + SQLAlchemy (SQLite by default) app for tracking a vinyl record collection.

## Rodando localmente

```bash
pip install -r requirements.txt
python app.py
```

`requirements.txt` tem só o que o servidor precisa em produção. Para rodar a
suíte de testes, instale também as dependências de desenvolvimento
(`requirements-dev.txt` já inclui o `requirements.txt`):

```bash
pip install -r requirements-dev.txt
python -m pytest
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
   - `MAX_UPLOAD_MB` — opcional, padrão `128`. Teto do upload em MB. As capas
     viajam no CSV em base64, então o export de uma coleção razoável já passa do
     limite antigo de 32MB e o import volta 413 antes mesmo de chegar no
     servidor. Se isso acontecer, aumente este valor.
   - `ANTHROPIC_API_KEY` — chave da API da Anthropic (console.anthropic.com).
     Não é a assinatura do Claude.ai; é cobrança separada por uso. Sem ela, o
     scan por foto continua visível no formulário, mas cada tentativa volta com
     um erro (HTTP 503) mostrado ali mesmo, sem preencher nada; o cadastro
     manual segue funcionando normalmente.
   - `MUSICBRAINZ_CONTACT` — e-mail de contato enviado no `User-Agent` para a
     MusicBrainz (obrigatório pela API deles).
   - `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — de um app registrado em
     developer.spotify.com. Sem eles, o campo de colar link do Spotify se
     comporta do mesmo jeito: continua visível e responde com o erro 503 ao ser
     usado. O scan por foto não é afetado.
   - `BACKUP_ENABLED` — opcional, padrão ligado. `0` desliga o backup diário
     (ver abaixo).

   As credenciais ficam só no servidor e não são enviadas para o navegador, por
   isso nenhuma das duas opções some da tela quando falta configuração — o que
   muda é a mensagem de erro que aparece ao tentar usar.
3. Em **Settings → Volumes**, crie um volume e monte-o em `/data`. Sem isso, o banco SQLite vive no filesystem efêmero do Railway e é apagado a cada deploy.
4. O Railway detecta `railway.toml`/`Procfile` automaticamente (Nixpacks + gunicorn).

Com o volume montado em `/data` e `DATA_DIR=/data`, o banco (`/data/vinyl.db`) persiste entre deploys e restarts — não é mais necessário exportar/importar CSV como backup manual antes de cada deploy. Os endpoints `/api/export` e `/api/import` continuam disponíveis para backups manuais opcionais.

## Backup diário

O servidor tira um snapshot do banco uma vez por dia e guarda **os últimos 5**.
Os arquivos ficam em `/data/backups/vinyl-AAAA-MM-DD.db`, no mesmo volume do
banco, e os mais antigos são apagados sozinhos.

Como funciona, e por que assim:

- O snapshot usa a API de backup online do SQLite, não um `cp`. O gunicorn está
  servindo enquanto o backup roda, e copiar o arquivo no meio de uma transação
  pode gravar uma escrita pela metade — um arquivo que parece backup e restaura
  como banco corrompido.
- O arquivo é escrito com nome temporário e só depois renomeado, então um
  backup interrompido nunca ocupa o nome do dia.
- Uma thread dentro do app roda no boot e de hora em hora. O nome com a data é
  o que garante um arquivo por dia: dois workers do gunicorn, um redeploy no
  meio da tarde ou uma batida de hora a mais não geram cópias extras. Ticar de
  hora em hora em vez de agendar um horário fixo também evita perder o dia
  quando o processo reinicia bem na hora marcada.
- Falha de backup (volume cheio, banco travado) é registrada no log e
  descartada: o app continua servindo a coleção normalmente.
- Sem SQLite não há backup. Se existir `DATABASE_URL` apontando para Postgres,
  a thread nem começa — não há arquivo para copiar.

Espaço: cada snapshot tem o tamanho do banco (hoje ~47MB, e cresce junto com as
capas), então 5 dias ocupam ~250MB além do banco.

### Baixar um backup

Em modo de edição, menu **⋯ → backups**: lista os 5 snapshots com data e
tamanho, e cada linha baixa o arquivo. Fica atrás da mesma senha do export —
um snapshot carrega capas, fotos das notas e as notas privadas.

### Restaurar

De propósito não existe botão de restaurar no app: a única coisa que um painel
de backup não pode fazer é sobrescrever a coleção viva por acidente. A
restauração é manual, no servidor:

```bash
railway ssh
cp /data/vinyl.db /data/vinyl.db.antes-de-restaurar   # rede de segurança
cp /data/backups/vinyl-2026-09-18.db /data/vinyl.db
```

Depois reinicie o serviço no Railway. Alternativa sem shell: baixe o snapshot
pelo menu de backups e restaure o conteúdo por `/api/import` a partir de um CSV
exportado desse arquivo.

Os backups vivem no mesmo volume do banco, então protegem contra import errado,
exclusão acidental e corrupção — não contra a perda do volume. Para uma cópia
fora do Railway, continue usando `/api/export` de vez em quando.
