# Monitor de Promoções — Pisos, Porcelanatos e Revestimentos

Monitora a internet (lojas grandes, pequenas, regionais e marketplaces) atrás
de promoções de pisos, porcelanatos, revestimentos cerâmicos e pisos
vinílicos, guarda histórico de preço por produto/loja e avisa no Telegram só
quando detecta uma **queda real** de preço — não uma etiqueta de "promoção"
permanente.

MVP para uso pessoal, com arquitetura já pronta para virar um SaaS
multiusuário pago no futuro (auth, planos, gancho de pagamento) sem cobrança
real implementada ainda.

## Como funciona

1. Um job diário (`worker.py`) roda buscas na [Firecrawl](https://www.firecrawl.dev)
   combinando categoria + termo de desconto (`config/categories.yml`),
   respeitando um orçamento mensal de créditos (veja "Custos" abaixo).
2. Cada resultado é raspado (a própria Firecrawl extrai o conteúdo da
   página), o preço é parseado do texto e gravado em `price_history`.
3. Um produto só dispara alerta quando o preço atual cai pelo menos
   `PRICE_DROP_THRESHOLD_PCT`% abaixo da mediana dos últimos
   `PRICE_BASELINE_WINDOW_DAYS` dias, e o preço anterior já estava estável há
   pelo menos `PRICE_MIN_STABLE_DAYS` dias — isso filtra "promoções" que na
   verdade são o preço de sempre (ver `app/pricing/detector.py`).
4. Alertas confirmados são enviados no Telegram e ficam visíveis no painel
   web (`main.py`) e no export CSV. O bot também manda uma mensagem de
   status no começo ("🔎 Começando a busca de hoje...") e no fim de cada
   rodada ("🏁 Busca concluída: X busca(s), Y preço(s) gravado(s), Z
   alerta(s), C cupom(ns)"), pra dar visibilidade mesmo quando não acha
   nenhuma promoção nova (ver `app/scheduler/jobs.py`).
5. Em paralelo, o mesmo texto raspado (`app/scraping/coupon_parser.py`) é
   varrido atrás de código de cupom — de graça, sem custo extra de crédito —
   e a busca também inclui sites agregadores de cupom dedicados
   (`coupon_site_domains`). Cupons achados aparecem no painel e no export
   CSV (`/export/csv?type=coupons`).

O painel web (`http://localhost:8000` local, ou a URL do Render em produção)
é protegido por login e tem uma página de **Configurações** (`/settings`)
onde dá pra colar a Firecrawl API key e o Telegram bot token/chat id direto
pela interface — sem precisar editar `.env` e reiniciar nada (esses valores
salvos ali têm prioridade sobre o `.env`). O botão **"▶ Rodar análise
agora"** no painel dispara a mesma busca do job diário, na hora, pra você
testar sem esperar o agendamento do GitHub Actions.

## App Desktop (.exe) — jeito mais simples de usar

Se você só quer rodar isso no seu PC sem mexer em terminal/Python toda vez,
tem um `.exe` do Windows que já embute tudo (Python, banco, painel):

- Ao abrir, ele sobe o painel local, abre automaticamente no seu navegador e
  fica com um ícone na bandeja do Windows (perto do relógio) rodando em
  segundo plano — busca promoções sozinho todo dia às 07:00 enquanto
  estiver aberto/o PC ligado.
- Clique com o botão direito no ícone da bandeja pra **"Abrir painel"**,
  **"Rodar análise agora"** ou **"Sair"**.
- Não precisa configurar nada de nuvem (Supabase/Render/GitHub Actions) —
  o banco fica local em `%APPDATA%\PromoMonitor\promo_monitor.db`.
- No primeiro login, use `admin@local.app` / `trocar123` — troque a senha e
  cole suas chaves da Firecrawl/Telegram em **Configurações** assim que
  abrir (veja as seções abaixo de como conseguir cada uma).

### Gerando o .exe você mesmo

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements-desktop.txt
.venv\Scripts\pyinstaller PromoMonitor.spec
```

O `.exe` final fica em `backend\dist\PromoMonitor.exe` — copie esse arquivo
pra onde quiser (não precisa mais do Python/venv pra rodá-lo, é
autocontido). Se editar o código, rode `pyinstaller PromoMonitor.spec` de
novo pra gerar uma versão atualizada.

**Nota sobre atualização de schema**: o `.exe` cria as tabelas do banco
direto (`Base.metadata.create_all`), sem rodar as migrações do Alembic —
funciona bem pra uma instalação nova, mas se uma versão futura do código
mudar o schema, um banco `.exe` já existente em `%APPDATA%` pode precisar
ser apagado (perde o histórico) ou migrado manualmente. Isso não afeta o
caminho de deploy em nuvem, que continua usando Alembic normalmente.

## Estrutura do repositório

```
backend/
  app/
    api/            rotas de autenticação (JWT) e assinatura/planos
    core/            config (.env), segurança (JWT), formatação, credenciais por usuário
    db/              models SQLAlchemy, seed, sessão
    scraping/        cliente Firecrawl, gerador de queries, gerenciador de cota, extração de preço
    pricing/         detecção de queda real de preço
    notifications/   envio Telegram
    scheduler/       job diário + agendador (modo loop, opcional)
    web/             painel (Jinja2): login, dashboard, configurações, export CSV
  alembic/           migrações do banco (usado no deploy em nuvem, não no .exe)
  scripts/           bootstrap.py (seed), telegram_get_chat_id.py
  tests/             suíte de testes (pytest)
  main.py            entrypoint do painel web (Render Web Service)
  worker.py          entrypoint do job de busca (chamado pelo GitHub Actions)
  desktop_app.py     entrypoint do app desktop (.exe): bandeja + painel + agendador
  PromoMonitor.spec  configuração do PyInstaller pra gerar o .exe
config/
  categories.yml     categorias, termos de busca, config de rodízio/cota
render.yaml          Blueprint do Render (painel web)
.github/workflows/   GitHub Actions (busca diária agendada)
```

## Setup local (Windows) — pra mexer no código

Se você só quer usar o app, veja a seção **App Desktop (.exe)** acima. Isto
aqui é pra rodar a partir do código-fonte (desenvolvimento).

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Copie `.env.example` para `.env` na raiz do projeto. Sem `DATABASE_URL`
definido, o app usa SQLite local automaticamente — zero setup de banco pra
desenvolver. Você pode deixar `FIRECRAWL_API_KEY`/`TELEGRAM_BOT_TOKEN` em
branco aqui e preenchê-los depois pelo painel (`/settings`), ou já colocar
no `.env` — os dois funcionam, o painel só tem prioridade quando preenchido.

```bash
cd backend
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python scripts\bootstrap.py      # cria planos + seu usuário + categorias
.venv\Scripts\python -m uvicorn main:app --reload   # painel em http://localhost:8000
```

Entre em `http://localhost:8000` com o e-mail/senha de
`BOOTSTRAP_USER_EMAIL`/`BOOTSTRAP_USER_PASSWORD` (do `.env`). Depois de
logar, vá em **Configurações** pra colar as chaves da Firecrawl/Telegram (e
trocar a senha, já que o valor do `.env` é só um placeholder) e volte pro
painel pra clicar em **"Rodar análise agora"**.

Em outro terminal, para testar uma rodada de busca manualmente:

```bash
cd backend
.venv\Scripts\python worker.py --run-now
```

### Rodando os testes

```bash
cd backend
.venv\Scripts\python -m pytest tests\ -v
```

## Configurar a Firecrawl

1. Crie uma conta em [firecrawl.dev](https://www.firecrawl.dev) (plano free:
   1.000 créditos/mês, sem cartão).
2. Pegue a API key no dashboard e cole em **Configurações** (`/settings`) no
   painel, no campo "Firecrawl API key" — ou coloque em `FIRECRAWL_API_KEY`
   no `.env`, se preferir.

## Configurar o Telegram

1. Fale com o [@BotFather](https://t.me/BotFather) no Telegram, crie um bot
   (`/newbot`) e copie o token.
2. Mande qualquer mensagem para o seu bot.
3. Rode `python scripts/telegram_get_chat_id.py` — ele lista os chat_ids que
   já mandaram mensagem pro bot.
4. Cole o token e o chat_id em **Configurações** (`/settings`) no painel —
   ou em `TELEGRAM_BOT_TOKEN`/`TELEGRAM_DEFAULT_CHAT_ID` no `.env`.

### Adicionar item mandando mensagem pro bot (só na nuvem)

Além de receber alertas, o bot também aceita comando: mande o nome de um
item direto pra ele (ex: `Fogão`) que ele já cria como novo item de busca e
confirma de volta. Só funciona pra chat_ids já configurados em
Configurações (qualquer outro é ignorado).

Pra ativar, entre em **Configurações** (`/settings`) no painel e clique em
"Ativar / atualizar webhook do Telegram" (precisa ter salvo o Telegram Bot
Token antes) — o próprio servidor registra a URL do webhook usando o token
já salvo, sem precisar rodar nada por fora. Só funciona no deploy na nuvem
(o `.exe` local roda em `127.0.0.1`, sem endereço público que o Telegram
consiga chamar).

Se mandar uma mensagem e não chegar resposta nenhuma, tem uma página de
diagnóstico em Configurações → "Mandei mensagem e não recebi resposta — o
que houve?" (`/settings/telegram-diagnostico`) que consulta o próprio
Telegram (`getWebhookInfo`) e mostra se o webhook está registrado
corretamente, se teve erro na última entrega e quais chat_ids estão
autorizados a adicionar item — pra comparar com o número que mandou a
mensagem.

Alternativa por linha de comando, se preferir:
`python scripts/register_telegram_webhook.py` (precisa de `TELEGRAM_BOT_TOKEN`
e `JWT_SECRET` iguais aos de produção no `.env` local).

## Custos

### Comparação de APIs de busca (dados verificados em ago/2026)

| API | Cota grátis/mês | Sem cartão? | Custo acima da cota | Busca + extração numa chamada? |
|---|---|---|---|---|
| **Firecrawl** (escolhida) | 1.000 créditos/mês | Sim | Hobby $16/mês → ~5.000 créditos/mês | Sim |
| Tavily | 1.000 créditos/mês | Sim | Pay-as-you-go $0,008/crédito ou ~$30/mês (4.000 créditos) | Não (só busca) |
| SerpAPI | 250 buscas/mês | Sim | Starter $25/mês → 1.000 buscas | Não diretamente (Google Shopping ajuda) |
| Google Custom Search JSON API | — | — | — | Fechada para novos clientes desde 2025 |
| Bing Search API | — | — | — | Descontinuada pela Microsoft em ago/2025 |

### Orçamento de créditos Firecrawl

Cada busca com raspagem dos top N resultados custa aprox. `2 + N` créditos.
Com `FIRECRAWL_SCRAPE_TOP_N=2` (padrão) e orçamento de
`FIRECRAWL_MONTHLY_CREDIT_BUDGET=900` (deixa margem sobre os 1.000 grátis):

- ~37 buscas/dia cabem confortavelmente no orçamento (900 ÷ 30 dias ÷ 4 créditos/busca).
- Cada item de busca (`/items`) gera queries nessa ordem de prioridade: (1)
  termo genérico + desconto, (2) uma busca dedicada em cada domínio de
  `marketplace_priority_domains` (Mercado Livre, Shopee, C&C, PJ Center,
  Mário Telhas — via `site:dominio.com.br`), (3) uma busca dedicada em cada
  domínio de `coupon_site_domains` (Cuponomia, Pelando, Méliuz — atrás de
  cupom de desconto), (4) variações de tamanho, se configuradas. O que sobra
  de orçamento sempre cobre os itens antes na lista primeiro — com 8+
  domínios forçados por item hoje, é comum que (3) e até (2) não caibam
  inteiros em dias de cota mais apertada.
- Categorias/itens revezam por dia (`categories_per_day` em
  `config/categories.yml`) em vez de rodar todos juntos — o
  `app/scraping/quota.py` calcula quantas buscas cabem hoje dividindo o
  orçamento restante pelos dias que faltam no mês, reduzindo o rodízio
  automaticamente perto do fim do mês em vez de estourar a cota. Quanto
  mais itens você cadastrar, menos frequente cada um é checado — dá pra
  compensar aumentando `FIRECRAWL_MONTHLY_CREDIT_BUDGET`,
  `categories_per_day`, ou reduzindo `FIRECRAWL_SCRAPE_TOP_N` ainda mais.
- Para mais abrangência, o próximo degrau é o plano Hobby da Firecrawl
  ($16/mês, ~5.000 créditos) — não é necessário para o MVP.

### Hospedagem (R$ 0/mês dentro dos limites gratuitos)

- **Banco de dados**: [Supabase](https://supabase.com) — Postgres free tier
  (necessário porque Render, Railway e Fly.io não garantem disco persistente
  de graça em 2026; ver comparação completa no histórico do projeto).
- **Painel web**: Render free Web Service (750h/mês, dorme após ~15min sem
  tráfego — aceitável para um painel pessoal, só demora um pouco pra
  "acordar" na primeira visita do dia).
- **Busca diária agendada**: GitHub Actions (2.000 min/mês grátis em repo
  privado, ilimitado em público) — Render free **não** tem Background
  Worker, por isso o agendamento roda fora dele.

## Deploy

### 1. Supabase (banco)

1. Crie um projeto em [supabase.com](https://supabase.com) (free tier).
2. Em Project Settings → Database → Connection string → URI, copie a
   connection string e troque `postgresql://` por `postgresql+psycopg2://`.

### 2. Render (painel web)

1. Suba este repo no GitHub.
2. Em [dashboard.render.com/blueprints](https://dashboard.render.com/blueprints),
   conecte o repo — o Render lê `render.yaml` automaticamente.
3. Preencha os campos marcados `sync: false` (DATABASE_URL do Supabase,
   FIRECRAWL_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_DEFAULT_CHAT_ID,
   JWT_SECRET, BOOTSTRAP_USER_EMAIL, BOOTSTRAP_USER_PASSWORD) no painel do
   Render — segredos não ficam no `render.yaml`/git.

### 3. GitHub Actions (busca diária)

Em Settings → Secrets and variables → Actions do seu repo, crie os secrets:
`DATABASE_URL`, `FIRECRAWL_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_DEFAULT_CHAT_ID`, `JWT_SECRET`, `BOOTSTRAP_USER_EMAIL`,
`BOOTSTRAP_USER_PASSWORD` — os mesmos valores usados no Render. O workflow
`.github/workflows/daily-search.yml` já está configurado para rodar todo dia
às 07:00 (horário de Brasília); dá pra disparar manualmente pela aba
"Actions" do GitHub a qualquer momento.

## Ressalvas legais

- **robots.txt**: a Firecrawl respeita `robots.txt` por padrão nas
  raspagens — não construímos scraping próprio que ignore isso.
- **Termos de uso de marketplaces**: Mercado Livre, Amazon e Shopee em geral
  proíbem scraping automatizado em seus ToS, mesmo que tecnicamente
  acessível. Para uso pessoal (não redistribuído, baixo volume) o risco é
  baixo, mas se este projeto virar um produto pago aberto a outras pessoas,
  isso precisa de revisão jurídica antes de escalar — o caminho mais seguro
  ali é usar APIs oficiais/de afiliados desses marketplaces em vez de raspar
  as páginas diretamente.
- Isto **não é aconselhamento jurídico**, só orientação de boas práticas.

## Arquitetura pensada para virar produto pago

- **Multi-tenant desde já**: toda tabela de negócio (`categories`,
  `search_runs`, `products`, `price_history`, `price_alerts`) tem `user_id`,
  mesmo com um único usuário hoje.
- **Auth real**: `app/api/auth.py` — login com e-mail/senha (bcrypt) +
  token JWT. Hoje só o usuário semeado (`scripts/bootstrap.py`) existe.
- **Planos e limites**: tabela `plans` (`max_searches_per_day`,
  `max_categories`, `max_notifications_per_day`, `price_cents`) e
  `subscriptions` já esboçadas em `app/db/models.py`.
- **Gancho de pagamento**: `POST /subscribe` (`app/api/subscribe.py`) grava a
  intenção de assinatura mas não cobra nada — é o ponto de extensão óbvio
  para integrar Stripe ou Mercado Pago depois.

## Próximos passos sugeridos

- Registro de novos usuários (hoje só existe o usuário semeado).
- Cobrança real via Stripe/Mercado Pago no endpoint `/subscribe`.
- Aplicar os limites de `plans` no scheduler (hoje o orçamento de créditos é
  global, não por usuário).
- Parser de preço dedicado por loja, se a heurística genérica
  (`app/scraping/price_parser.py`) errar muito em algum domínio específico.
