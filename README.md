# Tracken Analytics

Dashboard de métricas de uso do sistema (Login, Pop-up e futuras
funcionalidades), construído com **Streamlit + DuckDB + Pandas +
Plotly**, substituindo o Power BI. Mantém histórico acumulado: cada
importação de JSON soma-se ao que já existe, sem duplicar registros.

## Como executar

Na primeira execução (qualquer um dos modos abaixo) o banco
`data/analytics.duckdb` é criado automaticamente (schema vazio). Ele
**não é versionado** — é o histórico consolidado local de cada
máquina/ambiente.

### Local (Windows)

```powershell
.\scripts\run_local.ps1
```

O script cria o `.venv` se não existir, instala/atualiza as
dependências e sobe o Streamlit em `http://localhost:8501`.

Alternativa manual:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
streamlit run app.py
```

### Docker

```bash
docker build -t dash-tracken .
docker run -p 8501:8501 -v dash-tracken-data:/app/data dash-tracken
```

O volume `dash-tracken-data` garante que `analytics.duckdb` sobrevive a
`docker run`/restart do container — sem ele, os dados importados
seriam perdidos a cada novo container.

### Produção (Render)

O repositório tem um `render.yaml` (Blueprint) que provisiona:

- um Web Service Docker a partir deste `Dockerfile`;
- um **Persistent Disk** de 1GB montado em `/app/data`, para o
  `analytics.duckdb` sobreviver a redeploys — sem isso, qualquer novo
  deploy apagaria todo o histórico importado (disco de containers é
  efêmero por padrão).

Para publicar: conecte este repositório GitHub à sua conta Render e
aplique o Blueprint (New → Blueprint → selecione `dash-tracken`). Não
há variáveis de ambiente obrigatórias — a porta é lida de `$PORT`,
que a Render injeta automaticamente.

## Fluxo de uso

1. Abra **Importar Dados**, selecione um arquivo JSON.
2. Confira a prévia: registros encontrados, novos, existentes e
   inválidos.
3. Clique em **Importar dados** para persistir.
4. Vá em **Visão Geral** ou na página da métrica específica (Login,
   Pop-up) para ver KPIs, evolução e comparação semanal.
5. Consulte **Histórico de Importações** para auditar o que foi
   importado, quando e com que resultado.

Os dois arquivos de exemplo (`data/samples/login-19-08_26-08.json` e
`data/samples/popup-19-08_26-08.json` — fora do controle de versão, pois
contêm dados reais de uso) já foram importados para você validar o fluxo
imediatamente. Tente importar o mesmo arquivo de novo: o preview vai
mostrar 0 novos / todos existentes, comprovando a idempotência.

## Modelo de dados — como foi definido

Os dois JSONs fornecidos têm granularidades **diferentes**, o que guiou
o design:

- **Login** (`login-*.json`): `{"YYYY-MM-DD": total}` — já vem
  agregado por dia, sem quebra por usuário/empresa.
- **Pop-up** (`popup-*.json`): `{"YYYY-MM-DD": {"total": N, "usuarios":
  [{coduser, codemp, cliques, primeiro_clique, ultimo_clique}, ...]}}`
  — granularidade de (dia, usuário, empresa). O campo `total` é
  redundante (soma de `cliques`) e não é persistido, para não haver
  duas fontes de verdade.

Por isso o banco **não usa uma tabela genérica única** (isso forçaria
um modelo EAV desnecessariamente complexo para o volume de dados
atual). Cada métrica tem sua própria tabela, no formato que reflete sua
granularidade real:

```sql
metric_login_daily (
    date DATE PRIMARY KEY,
    total_logins INTEGER NOT NULL,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL
)

metric_popup_daily (
    date DATE, coduser VARCHAR, codemp VARCHAR,
    cliques INTEGER NOT NULL,
    primeiro_clique TIMESTAMP, ultimo_clique TIMESTAMP,
    import_run_id BIGINT, updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (date, coduser, codemp)
)

import_runs (
    id BIGINT PRIMARY KEY, metric_type VARCHAR, filename VARCHAR,
    imported_at TIMESTAMP, records_received/inserted/updated/ignored/invalid INTEGER,
    status VARCHAR, error_message VARCHAR
)
```

O que padroniza as métricas entre si não é o schema do banco, e sim a
interface Python `MetricDefinition` (`metrics/base.py`): toda métrica
declara sua chave natural, colunas de valor, DDL, e como parsear/validar
seu JSON. Importação, dashboard e navegação são genéricos sobre essa
interface — **nenhum dos dois compartilha tabela, mas os dois
compartilham todo o pipeline**.

### Deduplicação e idempotência

Cada métrica define sua **chave natural**:

- Login: `(date)` — um total por dia.
- Pop-up: `(date, coduser, codemp)` — confirmado no arquivo real que
  não há colisão dentro do mesmo dia.

Ao importar um arquivo, cada registro é comparado com o banco pela
chave natural:

| Situação | Ação |
|---|---|
| Chave não existe no banco | **Inserido** |
| Chave existe, valores iguais | **Ignorado** (nenhuma escrita) |
| Chave existe, algum valor mudou | **Atualizado** (UPSERT) |

Isso cobre tanto o caso "importei o mesmo arquivo duas vezes sem
querer" (tudo cai em ignorado) quanto "reenviei o dia de hoje com mais
cliques acumulados" (vira atualização, não duplicação). Validado com
teste automatizado: importar os dois arquivos de exemplo duas vezes
resulta em 0 novos / 0 atualizados na segunda vez.

## Arquitetura

```
app.py                  # monta a navegação (fixa + gerada a partir de METRICS)
metrics/                # o que cada métrica É: parse, validação, schema, chave natural
  base.py               #   MetricDefinition (a interface)
  login.py, popup.py    #   uma métrica = um módulo
  __init__.py           #   METRICS = {chave: definição}  <- registro central
services/
  database.py           #   ÚNICO lugar que conhece DuckDB (conexão + schema)
  importer.py            #   pipeline: parse -> valida -> detecta dup -> persiste
  metrics_service.py     #   KPIs, séries diárias, comparação semanal, ranking
repositories/
  metrics_repository.py  #   SELECT/UPSERT genéricos sobre qualquer MetricDefinition
  import_repository.py   #   CRUD da tabela import_runs
components/               # widgets Streamlit reutilizáveis (cards, gráficos, filtro de período)
views/                    # uma função de página por tela; sem lógica de negócio dentro delas
utils/                    # logging e injeção de CSS
assets/styles.css         # visual "SaaS", sem exagero de efeitos
data/analytics.duckdb     # histórico consolidado (gitignored)
logs/app.log              # log de importações e erros
```

### Por que `views/` (funções) em vez de `pages/` (arquivos)

O Streamlit permite montar a navegação programaticamente
(`st.navigation` + `st.Page`) a partir de funções, não só de arquivos.
Isso foi usado de propósito: **as páginas de métrica (Login, Pop-up) são
geradas em loop a partir de `metrics.METRICS`** (`app.py`). Adicionar
uma métrica nova no futuro é registrar um módulo em `metrics/` — nenhum
arquivo de página novo, nenhuma duplicação de layout/lógica.

### Extensibilidade pensada, sem implementar agora

- **Trocar DuckDB por PostgreSQL**: toda query mora em `repositories/`
  e usa SQL ANSI-padrão (`INSERT ... ON CONFLICT ... DO UPDATE` já é
  sintaxe compatível com Postgres). Só `services/database.py` precisa
  mudar.
- **API/webhook de importação automática**: `services/importer.py` já
  separa "receber bytes JSON" de "quem os enviou" — reaproveitável por
  um endpoint futuro sem tocar na lógica de negócio.
- **Analista de IA**: `services/metrics_service.py` já centraliza os
  cálculos; é a camada que vai gerar o contexto estruturado para um
  LLM no futuro.
- **Nova métrica**: um módulo em `metrics/` + uma entrada em
  `metrics/__init__.py`. Sem tocar em `app.py`, `importer.py`,
  `metrics_service.py` ou nas views.

## Cache

- `st.cache_resource` na conexão DuckDB (`services/database.py`) —
  reaberta uma única vez por sessão.
- `st.cache_data` nas séries diárias usadas pelos gráficos
  (`services/metrics_service.load_daily_series_cached`) — invalidado
  explicitamente (`clear_cache()`) sempre que uma importação é
  confirmada, para o dashboard nunca mostrar dados desatualizados.

## Logging

`utils/logging_config.py` grava em `logs/app.log` (e no console):
início/fim de importações com contagens, falhas de leitura de JSON e
erros de banco. Sem infraestrutura adicional nesta versão.

## Testado

- Importação dos dois arquivos reais fornecidos (login e popup).
- Reimportação dos mesmos arquivos — confirmado 0 registros novos, 0
  atualizados na segunda vez (idempotência).
- Todas as páginas (Visão Geral, Login, Pop-up, Importar Dados,
  Histórico) renderizadas sem exceções via `streamlit.testing.v1.AppTest`.
