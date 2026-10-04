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
   - `UMAMI_WEBSITE_ID` — opcional. ID do site no Umami (cloud.umami.is →
     Settings → Websites). Sem ela, o script de analytics nem é incluído na
     página, então rodar localmente não conta visitas.
   - `UMAMI_SCRIPT_URL` — opcional, padrão `https://cloud.umami.is/script.js`.
     Só muda se o Umami for self-hosted.

   As credenciais ficam só no servidor e não são enviadas para o navegador, por
   isso nenhuma das duas opções some da tela quando falta configuração — o que
   muda é a mensagem de erro que aparece ao tentar usar.
3. Em **Settings → Volumes**, crie um volume e monte-o em `/data`. Sem isso, o banco SQLite vive no filesystem efêmero do Railway e é apagado a cada deploy.
4. O Railway detecta `railway.toml`/`Procfile` automaticamente (Nixpacks + gunicorn).

Com o volume montado em `/data` e `DATA_DIR=/data`, o banco (`/data/vinyl.db`) persiste entre deploys e restarts — não é mais necessário exportar/importar CSV como backup manual antes de cada deploy. Os endpoints `/api/export` e `/api/import` continuam disponíveis para backups manuais opcionais.

## Playlists no Spotify

- **Admin page** (⋯ → admin, edit mode): places, CSV export/import, backups, and a Spotify playlist → wishlist tool that names each song's studio album with Claude and checks MusicBrainz for a vinyl pressing.

Em modo de edição, menu **⋯ → spotify playlists** lista as playlists que o app
criou na sua conta e permite criar novas a partir de filtros. Todas usam só os
discos que você tem (não a wishlist) e que têm link do Spotify, na ordem de
compra. Filtros (todos opcionais, combinados com E):

- **Músicas** — só as curtidas (padrão) ou todas as faixas de cada álbum. As
  curtidas são casadas pelo título com as faixas do álbum no Spotify; as que
  não casam aparecem em "not found", com a capa do disco.
- **Ano de lançamento** — de / até.
- **Gênero** e **Comprado em** — qualquer um dos escolhidos.
- **Nota** — mínimo da Pepe e/ou da Jenni, exigindo as duas (and) ou uma (or).
- **Comprado entre** — datas de / até (o mesmo dia nas duas = data exata).

Pedir os mesmos filtros de novo não cria outra playlist: a que já existe é
sincronizada. As duas playlists antigas (**Zucoloto Vinyl Collection** e
**— Liked**) viram itens da lista e continuam sendo as mesmas no Spotify.
Apagar uma playlist no painel apaga também no Spotify.

Cada **sync** cria a playlist se ela não existir (privada) e, se existir,
adiciona o que falta no fim e remove o que não pertence mais (música
descurtida, link removido, disco vendido). A playlist espelha a coleção: uma
faixa adicionada à mão nela também é removida no próximo sync.

Configuração, uma vez só:

1. No app em developer.spotify.com (o mesmo do `SPOTIFY_CLIENT_ID`), em
   **Redirect URIs**, adicione `https://<seu-domínio>/api/spotify/callback`. O
   painel mostra a URI exata antes de conectar. Localmente, o Spotify só aceita
   http em `http://127.0.0.1:5000/api/spotify/callback` (não `localhost`).
2. Se o app estiver em development mode, a sua conta do Spotify precisa estar
   em **User Management** do app.
3. Opcional: `SPOTIFY_REDIRECT_URI` força a URI, se a detectada estiver errada.
4. No painel, **connect spotify** e autorize. O login fica salvo no banco.

O primeiro sync lê um álbum por request (o Spotify não tem mais endpoint em
lote), então pode levar alguns minutos; o painel mostra o progresso. Os
tracklists ficam em cache, e os syncs seguintes só leem os discos novos.

## Gêneros

A lista de gêneros fica em `genres.py` (19 gêneros por estilo; o antigo
"MPB & Samba" foi aposentado). O formulário só oferece esses, o servidor recusa
qualquer outro ao criar/editar, e o scan/busca só deixa o Claude responder com
eles. Cada gênero tem uma cor em `GENRE_PALETTE` (`templates/index.html`); o
`tests/test_genres.py` falha se as duas listas divergirem.

Para mover um banco existente para a lista nova, gere o `genre_mapping.csv` a
partir de um export completo e rode:

```bash
python scripts/migrate_genres.py genre_mapping.csv --dry-run   # só mostra
python scripts/migrate_genres.py genre_mapping.csv --apply     # backup + grava
```

Só a coluna `genre` é alterada, casando por `id` e conferindo artista e álbum.
Um banco restaurado de CSV tem ids novos (o import renumera); nesse caso use
`--fallback-by-name`. Sem `--db`, usa o mesmo banco do app (`$DATA_DIR/vinyl.db`).

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
