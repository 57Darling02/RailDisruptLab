from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

from core.types import BaseContext

REQUIRED_COLUMNS = ["train_id", "station", "arrival_time", "departure_time"]
CANCELED_COLUMN = "is_canceled"


def _normalize_columns(columns: List[str]) -> List[str]:
    mapping = {
        "train_id": "train_id",
        "trainid": "train_id",
        "train_ID": "train_id",
        "station": "station",
        "arrival_time": "arrival_time",
        "arrivaltime": "arrival_time",
        "departure_time": "departure_time",
        "departuretime": "departure_time",
        "is_canceled": CANCELED_COLUMN,
        "iscanceled": CANCELED_COLUMN,
        "canceled": CANCELED_COLUMN,
        "cancelled": CANCELED_COLUMN,
        "cancellation": CANCELED_COLUMN,
    }
    normalized: List[str] = []
    for col in columns:
        key = str(col).strip()
        lookup = key.lower().replace(" ", "_")
        compact = lookup.replace("_", "")
        normalized.append(mapping.get(key, mapping.get(lookup, mapping.get(compact, lookup))))
    return normalized


def _parse_time_column(df: pd.DataFrame, column: str) -> pd.Series:
    text = df[column].astype(str).str.strip()
    text = text.replace({"": pd.NA, "nan": pd.NA, "NaT": pd.NA})
    parsed = pd.to_datetime(text, format="%H:%M:%S", errors="coerce")
    fallback = pd.to_datetime(text, format="%H:%M", errors="coerce")
    parsed = parsed.fillna(fallback)
    return parsed.dt.strftime("%H:%M:%S").where(parsed.notna(), None)


def _parse_bool_column(df: pd.DataFrame, column: str) -> pd.Series:
    text = df[column].fillna("").astype(str).str.strip().str.lower()
    return text.isin({"1", "1.0", "true", "t", "yes", "y", "canceled", "cancelled"})


def read_timetable(path: Path, sheet_name: str = "Sheet1") -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df.columns = _normalize_columns(df.columns.tolist())

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {path}: {missing}")

    columns = REQUIRED_COLUMNS + ([CANCELED_COLUMN] if CANCELED_COLUMN in df.columns else [])
    df = df[columns].copy()
    df["train_id"] = df["train_id"].astype(str).str.strip()
    df["station"] = df["station"].astype(str).str.strip()
    df["arrival_time"] = _parse_time_column(df, "arrival_time")
    df["departure_time"] = _parse_time_column(df, "departure_time")
    if CANCELED_COLUMN in df.columns:
        df[CANCELED_COLUMN] = _parse_bool_column(df, CANCELED_COLUMN)
    else:
        df[CANCELED_COLUMN] = False
    return df


def timetable_from_base_context(context: BaseContext) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "train_id": row.train_id,
                "station": row.station,
                "arrival_time": row.arrival_time,
                "departure_time": row.departure_time,
                CANCELED_COLUMN: False,
            }
            for row in context.validated.timetable_rows
        ],
        columns=REQUIRED_COLUMNS + [CANCELED_COLUMN],
    )
