# Tracken Analytics

Dashboard de métricas (Login, Pop-up, Disparos E-mail e Amazon) em **Streamlit + PostgreSQL**.
Cada importação soma ao histórico existente, sem duplicar registros.

## Rodar local

Crie `.streamlit/secrets.toml` a partir de `.streamlit/secrets.toml.example` (com a `DATABASE_URL` do Postgres) e rode:

```powershell
.\scripts\run_local.ps1
```

Abre em `http://localhost:8501`. As tabelas são criadas sozinhas na primeira execução.

## Produção

Streamlit Community Cloud, branch `main`, arquivo `app.py`. A `DATABASE_URL` vai em *Advanced settings → Secrets*.
Todo push na `main` publica automaticamente.

O banco é o Supabase (plano gratuito): use a connection string do **Session pooler** e lembre que o projeto
**pausa após ~7 dias sem uso**, o que derruba o app até ser restaurado no painel.

## Importar dados

Em **Importar Dados**, escolha o arquivo, confira a prévia e confirme. Reimportar o mesmo arquivo não duplica nada.

| Métrica | Arquivo |
|---|---|
| Login | JSON `{"AAAA-MM-DD": total}` |
| Pop-up | JSON por dia, com a lista de usuários |
| Disparos E-mail | CSV nomeado `email_<cliente>_<campanha>.csv` (ex.: `email_clientea_123.csv`) |
| Amazon | Excel com abas `traffic` e `funnel`; importe o mesmo arquivo duas vezes, uma por métrica |

## Nova métrica

Crie um módulo em `metrics/` (copie `login.py` como modelo) e registre em `metrics/__init__.py`.
A página e a importação aparecem sozinhas.
