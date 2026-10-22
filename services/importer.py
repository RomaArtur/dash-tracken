"""Pipeline de importação: validação -> normalização -> detecção de
duplicidade/idempotência -> preview -> persistência.

A idempotência é garantida comparando a chave natural de cada métrica
(`MetricDefinition.key_columns`) com o que já está no banco:

  - chave não existe no banco            -> registro NOVO (será inserido)
  - chave existe e valores são iguais    -> INALTERADO (ignorado, nada é escrito)
  - chave existe e algum valor mudou     -> ATUALIZADO (UPSERT)

Isso significa que importar o mesmo arquivo duas vezes é seguro: na
segunda vez todos os registros caem em "inalterado" e nenhuma escrita é
feita além do próprio registro em import_runs.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass

import pandas as pd

from metrics.base import MetricDefinition
from repositories import import_repository, metrics_repository
from services.database import get_connection

logger = logging.getLogger(__name__)


class ImportValidationError(Exception):
    """Erro ao ler ou interpretar o arquivo de métricas enviado."""


@dataclass
class ImportPreview:
    metric: MetricDefinition
    filename: str
    total_parsed: int
    valid_df: pd.DataFrame
    invalid_df: pd.DataFrame
    new_df: pd.DataFrame
    updated_df: pd.DataFrame
    unchanged_df: pd.DataFrame

    @property
    def n_new(self) -> int:
        return len(self.new_df)

    @property
    def n_updated(self) -> int:
        return len(self.updated_df)

    @property
    def n_unchanged(self) -> int:
        return len(self.unchanged_df)

    @property
    def n_invalid(self) -> int:
        return len(self.invalid_df)

    @property
    def n_existing(self) -> int:
        return self.n_updated + self.n_unchanged


def load_json(file_bytes: bytes) -> dict:
    try:
        return json.loads(file_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ImportValidationError(f"Arquivo JSON inválido: {exc}") from exc


def load_csv(file_bytes: bytes) -> pd.DataFrame:
    """Lê um CSV com vírgula, ponto-e-vírgula ou tabulação (ex.:
    CRM de e-mail marketing). Tenta utf-8-sig primeiro (cobre o BOM que
    editores/exportadores do Windows costumam gravar) e cai para
    cp1252, comum em exports de ferramentas BR quando não é UTF-8."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ImportValidationError("Não foi possível decodificar o arquivo CSV (encoding desconhecido).")

    try:
        header = text.splitlines()[0] if text.splitlines() else ""
        try:
            separator = csv.Sniffer().sniff(header, delimiters=",;\t").delimiter
        except csv.Error:
            separator = ";"
        return pd.read_csv(io.StringIO(text), sep=separator, dtype=str)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ImportValidationError(f"Arquivo CSV inválido: {exc}") from exc


def load_xlsx(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    """Lê uma aba específica de um arquivo Excel de múltiplas abas (ex.:
    o relatório semanal da Amazon, que traz 'traffic' e 'funnel' juntos
    no mesmo arquivo — cada aba vira uma métrica registrada à parte, ver
    metrics/amazon_traffic.py e metrics/amazon_funnel.py)."""
    try:
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, engine="openpyxl")
    except ValueError as exc:
        raise ImportValidationError(f"Não foi possível ler a aba '{sheet_name}' do arquivo Excel: {exc}") from exc


def _comparable(series: pd.Series) -> pd.Series:
    """Normaliza uma coluna para comparação textual entre o valor recém
    parseado e o que já está no banco. Sem isso, uma coluna numérica
    nula (ex.: metrics/amazon_funnel.py: siv_approved_indicator) volta
    do banco como float (1.0) — porque `pandas.DataFrame(cur.fetchall())`
    promove pra float qualquer coluna que misture inteiros com None —
    enquanto o valor recém-parseado é int (1); '1' != '1.0' geraria um
    falso positivo de 'registro mudou' a cada reimportação. Constrói o
    resultado célula a célula (em vez de `.map()`/`.astype(str)`
    vetorizado) de propósito: em colunas de data, o pandas às vezes
    reconverte `None` de volta pra `NaT` durante essas operações
    vetorizadas, e duas floats NaN nunca são iguais entre si (`nan !=
    nan`), quebrando a comparação mesmo depois de normalizar."""

    def normalize(value) -> str:
        if pd.isna(value):
            return "None"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    return pd.Series([normalize(v) for v in series], index=series.index)


def _empty_preview(metric: MetricDefinition, filename: str, parsed: pd.DataFrame) -> ImportPreview:
    return ImportPreview(metric, filename, 0, parsed, parsed, parsed, parsed, parsed)


def build_preview(
    metric: MetricDefinition, filename: str, raw: dict | pd.DataFrame, context: dict | None = None
) -> ImportPreview:
    try:
        parsed = metric.parse(raw, context or {})
    except Exception as exc:
        logger.exception("Falha ao normalizar arquivo %s", filename)
        raise ImportValidationError(
            f"Não foi possível interpretar o arquivo para a métrica '{metric.label}': {exc}"
        ) from exc

    if parsed.empty:
        return _empty_preview(metric, filename, parsed)

    valid_df, invalid_df = metric.validate(parsed)

    key_cols = list(metric.key_columns)
    value_cols = list(metric.value_columns)
    keep_cols = key_cols + value_cols

    if valid_df.empty:
        empty_keep = pd.DataFrame(columns=keep_cols)
        return ImportPreview(metric, filename, len(parsed), valid_df, invalid_df, empty_keep, empty_keep, empty_keep)

    conn = get_connection()
    existing_df = metrics_repository.fetch_existing_keys(conn, metric)
    if not existing_df.empty and metric.date_column in existing_df.columns:
        # Normaliza a coluna de data para date() puro, que é o que
        # metric.validate() produz, para o merge abaixo funcionar
        # corretamente independentemente do tipo retornado pelo driver.
        existing_df[metric.date_column] = pd.to_datetime(existing_df[metric.date_column]).dt.date

    if existing_df.empty:
        new_df = valid_df[keep_cols].copy()
        updated_df = pd.DataFrame(columns=keep_cols)
        unchanged_df = pd.DataFrame(columns=keep_cols)
    else:
        merged = valid_df[keep_cols].merge(
            existing_df, on=key_cols, how="left", suffixes=("", "_existing"), indicator=True
        )
        new_df = merged[merged["_merge"] == "left_only"][keep_cols].copy()
        both_df = merged[merged["_merge"] == "both"].copy()

        if both_df.empty:
            updated_df = pd.DataFrame(columns=keep_cols)
            unchanged_df = pd.DataFrame(columns=keep_cols)
        else:
            changed_mask = pd.Series(False, index=both_df.index)
            for col in value_cols:
                existing_col = f"{col}_existing" if f"{col}_existing" in both_df.columns else col
                changed_mask |= _comparable(both_df[col]) != _comparable(both_df[existing_col])
            updated_df = both_df.loc[changed_mask, keep_cols].copy()
            unchanged_df = both_df.loc[~changed_mask, keep_cols].copy()

    return ImportPreview(
        metric=metric,
        filename=filename,
        total_parsed=len(parsed),
        valid_df=valid_df,
        invalid_df=invalid_df,
        new_df=new_df,
        updated_df=updated_df,
        unchanged_df=unchanged_df,
    )


def commit_import(preview: ImportPreview) -> int:
    """Persiste os registros novos/atualizados e grava a execução no
    histórico de importações. Registros inalterados não geram escrita."""
    conn = get_connection()
    frames = [d for d in (preview.new_df, preview.updated_df) if not d.empty]
    to_write = pd.concat(frames, ignore_index=True) if frames else preview.new_df.copy()

    status = "sucesso" if preview.n_invalid == 0 else "parcial"
    error_message = f"{preview.n_invalid} registro(s) inválido(s) ignorado(s)." if preview.n_invalid else None

    try:
        run_id = import_repository.create_run(
            conn,
            metric_type=preview.metric.key,
            filename=preview.filename,
            records_received=preview.total_parsed,
            records_inserted=preview.n_new,
            records_updated=preview.n_updated,
            records_ignored=preview.n_unchanged,
            records_invalid=preview.n_invalid,
            status=status,
            error_message=error_message,
        )
        metrics_repository.upsert(conn, preview.metric, to_write, run_id)
        from services.metrics_service import clear_cache

        clear_cache()
    except Exception as exc:
        logger.exception("Falha ao persistir importação de %s", preview.filename)
        import_repository.create_run(
            conn,
            metric_type=preview.metric.key,
            filename=preview.filename,
            records_received=preview.total_parsed,
            records_inserted=0,
            records_updated=0,
            records_ignored=0,
            records_invalid=preview.n_invalid,
            status="erro",
            error_message=str(exc),
        )
        raise

    logger.info(
        "Importação concluída: %s (%s) - novos=%d atualizados=%d ignorados=%d invalidos=%d",
        preview.filename,
        preview.metric.key,
        preview.n_new,
        preview.n_updated,
        preview.n_unchanged,
        preview.n_invalid,
    )
    return run_id


def delete_import(run_id: int) -> int:
    """Desfaz uma execução de importação: remove seu registro do
    histórico e os registros de métrica que ainda apontam pra ela
    (import_run_id) — registros já sobrescritos por uma importação mais
    recente não são afetados, só o que essa execução específica deixou.
    Retorna quantos registros de métrica foram removidos."""
    conn = get_connection()
    run = import_repository.get_run(conn, run_id)
    if run is None:
        raise ImportValidationError(f"Execução de importação #{run_id} não encontrada.")

    from metrics import METRICS

    metric = METRICS.get(run["metric_type"])
    deleted_count = 0
    with conn.transaction():
        if metric is not None:
            deleted_count = metrics_repository.delete_by_import_run(conn, metric, run_id)
        import_repository.delete_run(conn, run_id)

    from services.metrics_service import clear_cache

    clear_cache()
    logger.info("Importação #%d excluída (%s) - %d registro(s) removido(s)", run_id, run["filename"], deleted_count)
    return deleted_count
