"""Minimal BigQuery REST helpers for the batch pipeline (ADC credentials, no extra deps).

Tables live in <VERTEX_PROJECT>.gene_summaries_batch (location US), except the Claude
image-check tables: Claude batch jobs run in a single region (us-east5) and can only read
and write a dataset in that region, gene_summaries_check.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import google.auth
import requests
from google.auth.transport.requests import AuthorizedSession

PROJECT = "scilifelab-hpa-proj-1"
DATASET = "gene_summaries_batch"
LOCATION = "US"
CHECK_DATASET = "gene_summaries_check"
LOCATIONS = {DATASET: LOCATION, CHECK_DATASET: "us-east5"}
API = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}"
UPLOAD = f"https://bigquery.googleapis.com/upload/bigquery/v2/projects/{PROJECT}/jobs"

REQUEST_SCHEMA = [
    {"name": "key", "type": "STRING", "mode": "REQUIRED"},
    {"name": "request", "type": "JSON", "mode": "REQUIRED"},
]

_session: AuthorizedSession | None = None


def session() -> AuthorizedSession:
    global _session
    if _session is None:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(creds)
    return _session


def table_uri(table: str, dataset: str = DATASET) -> str:
    return f"bq://{PROJECT}.{dataset}.{table}"


def ensure_dataset(dataset: str = DATASET) -> None:
    r = session().post(f"{API}/datasets", json={
        "datasetReference": {"projectId": PROJECT, "datasetId": dataset}, "location": LOCATIONS[dataset],
    })
    if r.status_code not in (200, 409):  # 409 = already exists
        raise RuntimeError(f"dataset create failed: {r.status_code} {r.text[:300]}")


def _wait(job_id: str, location: str = LOCATION) -> dict:
    while True:
        j = session().get(f"{API}/jobs/{job_id}", params={"location": location}).json()
        if j["status"]["state"] == "DONE":
            if "errorResult" in j["status"]:
                raise RuntimeError(f"BigQuery job failed: {j['status'].get('errors', j['status']['errorResult'])}")
            return j
        time.sleep(3)


def load_jsonl(path: Path, table: str, schema: list[dict] = REQUEST_SCHEMA, append: bool = False,
               dataset: str = DATASET) -> int:
    """Upload a newline-delimited JSON file into DATASET.table (replacing it, or adding to it
    with append=True). Returns the number of rows loaded."""
    ensure_dataset(dataset)
    location = LOCATIONS[dataset]
    job = {
        "jobReference": {"projectId": PROJECT, "location": location},
        "configuration": {"load": {
            "destinationTable": {"projectId": PROJECT, "datasetId": dataset, "tableId": table},
            "sourceFormat": "NEWLINE_DELIMITED_JSON",
            "schema": {"fields": schema},
            "writeDisposition": "WRITE_APPEND" if append else "WRITE_TRUNCATE",
        }},
    }
    r = session().post(f"{UPLOAD}?uploadType=resumable", json=job)
    r.raise_for_status()
    print(f"uploading {path.stat().st_size / 1e6:.0f} MB to {dataset}.{table} ...", flush=True)
    with path.open("rb") as f:
        r = session().put(r.headers["Location"], data=f, headers={"Content-Type": "application/octet-stream"})
    r.raise_for_status()
    j = _wait(r.json()["jobReference"]["jobId"], location)
    rows = int(j["statistics"]["load"]["outputRows"])
    print(f"loaded {rows} rows -> {table_uri(table, dataset)}")
    return rows


def query(sql: str, page_size: int = 5000) -> Iterator[dict]:
    """Run a standard-SQL query and yield rows as {column: value} dicts (values are strings/None)."""
    r = session().post(f"{API}/jobs", json={
        "jobReference": {"projectId": PROJECT, "location": LOCATION},
        "configuration": {"query": {"query": sql, "useLegacySql": False}},
    })
    r.raise_for_status()
    job_id = r.json()["jobReference"]["jobId"]
    _wait(job_id)
    token = None
    while True:
        params = {"location": LOCATION, "maxResults": page_size}
        if token:
            params["pageToken"] = token
        page = session().get(f"{API}/queries/{job_id}", params=params).json()
        names = [f["name"] for f in page["schema"]["fields"]]
        for row in page.get("rows", []):
            yield {n: c["v"] for n, c in zip(names, row["f"])}
        token = page.get("pageToken")
        if not token:
            return


def query_to_table(sql: str, table: str) -> int:
    """Run a query and store its result in DATASET.table (replacing it). Returns row count."""
    r = session().post(f"{API}/jobs", json={
        "jobReference": {"projectId": PROJECT, "location": LOCATION},
        "configuration": {"query": {
            "query": sql, "useLegacySql": False,
            "destinationTable": {"projectId": PROJECT, "datasetId": DATASET, "tableId": table},
            "writeDisposition": "WRITE_TRUNCATE",
        }},
    })
    r.raise_for_status()
    _wait(r.json()["jobReference"]["jobId"])
    meta = session().get(f"{API}/datasets/{DATASET}/tables/{table}").json()
    return int(meta["numRows"])


_column_cache: dict[str, list[str]] = {}


def _columns(table: str, dataset: str = DATASET) -> list[str]:
    key = f"{dataset}.{table}"
    if key not in _column_cache:
        t = session().get(f"{API}/datasets/{dataset}/tables/{table}")
        t.raise_for_status()
        _column_cache[key] = [f["name"] for f in t.json()["schema"]["fields"]]
    return _column_cache[key]


def list_rows(table: str, start: int, n: int, dataset: str = DATASET) -> list[dict]:
    """Rows [start, start+n) of dataset.table as {column: value} dicts (free, no query job)."""
    names = _columns(table, dataset)
    for attempt in range(6):  # retry dropped connections / 5xx with backoff
        try:
            page = session().get(f"{API}/datasets/{dataset}/tables/{table}/data",
                                 params={"startIndex": start, "maxResults": n}, timeout=120)
            if page.status_code < 500:
                break
        except requests.RequestException:
            if attempt == 5:
                raise
        time.sleep(min(60, 5 * 2**attempt))
    page.raise_for_status()
    return [{k: c["v"] for k, c in zip(names, row["f"])} for row in page.json().get("rows", [])]
