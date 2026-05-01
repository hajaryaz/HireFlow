"""
ETL Pipeline — Bronze → Silver → Gold
Called by Airflow after scraping is done.
"""

import logging
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from db import get_engine

log = logging.getLogger(__name__)

# ── Title normalization map ────────────────────────────────────────────────────
TITLE_MAP = {
    # Data & AI
    "data scientist": "Data Scientist",
    "data engineer": "Data Engineer",
    "data analyst": "Data Analyst",
    "analyste data": "Data Analyst",
    "ingénieur data": "Data Engineer",
    "consultant data": "Data Analyst",
    "machine learning": "Machine Learning Engineer",
    "deep learning": "Deep Learning Engineer",
    "mlops": "MLOps Engineer",
    "bi analyst": "BI Analyst",
    "business intelligence": "BI Analyst",
    "data architect": "Data Architect",
    "nlp": "NLP Engineer",
    "computer vision": "Computer Vision Engineer",
    "ai engineer": "AI Engineer",
    # Software
    "software engineer": "Software Engineer",
    "backend": "Backend Developer",
    "front end": "Frontend Developer",
    "frontend": "Frontend Developer",
    "full stack": "Full Stack Developer",
    "fullstack": "Full Stack Developer",
    "développeur": "Software Developer",
    "developpeur": "Software Developer",
    # DevOps & Cloud
    "devops": "DevOps Engineer",
    "cloud engineer": "Cloud Engineer",
    # Security
    "cybersecurity": "Cybersecurity Engineer",
    "security analyst": "Security Analyst",
    # Management
    "product manager": "Product Manager",
    "scrum master": "Scrum Master",
    "chef de projet": "Project Manager",
}

def normalize_title(raw_title: str) -> str:
    if not raw_title:
        return "Other"
    lower = raw_title.lower()
    for key, normalized in TITLE_MAP.items():
        if key in lower:
            return normalized
    return "Other"

def parse_date(date_str: str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt[:len(date_str[:19])]).date()
        except Exception:
            continue
    return None

# ── BRONZE → load raw jobs ─────────────────────────────────────────────────────

def load_to_bronze(jobs: list[dict]) -> int:
    if not jobs:
        log.warning("No jobs to load into Bronze.")
        return 0

    engine = get_engine()
    df = pd.DataFrame(jobs)

    # Replace NaN with empty string
    df = df.fillna("")

    inserted = 0
    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(text("""
                INSERT INTO jobs_bronze
                    (title, company, location, date_posted, job_url,
                     search_keyword, scraped_at, salary, contract_type, source, description)
                VALUES
                    (:title, :company, :location, :date_posted, :job_url,
                     :search_keyword, :scraped_at, :salary, :contract_type, :source, :description)
            """), dict(row))
            inserted += 1

    log.info(f"[Bronze] Inserted {inserted} raw jobs.")
    return inserted

# ── BRONZE → SILVER ────────────────────────────────────────────────────────────

def bronze_to_silver() -> int:
    engine = get_engine()

    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM jobs_bronze", conn)

    if df.empty:
        log.warning("[Silver] Bronze table is empty.")
        return 0

    # Normalize
    df["title_normalized"] = df["title"].apply(normalize_title)
    df["date_posted_clean"] = df["date_posted"].apply(parse_date)

    # Drop rows with no URL (can't deduplicate without it)
    df = df[df["job_url"].str.strip() != ""]

    # Deduplicate by URL — keep most recent
    df = df.sort_values("scraped_at", ascending=False)
    df = df.drop_duplicates(subset=["job_url"], keep="first")

    inserted = 0
    with engine.begin() as conn:
        # Clear silver before reload (idempotent)
        conn.execute(text("DELETE FROM jobs_silver"))

        for _, row in df.iterrows():
            conn.execute(text("""
                INSERT INTO jobs_silver
                    (title_normalized, company, location, date_posted,
                     job_url, salary, contract_type, source, description)
                VALUES
                    (:title_normalized, :company, :location, :date_posted,
                     :job_url, :salary, :contract_type, :source, :description)
                ON DUPLICATE KEY UPDATE
                    title_normalized = VALUES(title_normalized),
                    company          = VALUES(company)
            """), {
                "title_normalized": row["title_normalized"],
                "company":          str(row.get("company", "")),
                "location":         str(row.get("location", "")),
                "date_posted":      row["date_posted_clean"],
                "job_url":          row["job_url"],
                "salary":           str(row.get("salary", "")),
                "contract_type":    str(row.get("contract_type", "")),
                "source":           str(row.get("source", "")),
                "description":      str(row.get("description", "")),
            })
            inserted += 1

    log.info(f"[Silver] {inserted} clean jobs written.")
    return inserted

# ── SILVER → GOLD ──────────────────────────────────────────────────────────────

def silver_to_gold() -> int:
    engine = get_engine()

    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM jobs_silver", conn)

    if df.empty:
        log.warning("[Gold] Silver table is empty.")
        return 0

    # Build description_text for NLP matching - utilise la VRAIE description
    df["description_text"] = df["description"].fillna("").str.strip()

    # Si description vide, utilise une combinaison de fallback
    mask_empty = df["description_text"] == ""
    df.loc[mask_empty, "description_text"] = (
        df.loc[mask_empty, "title_normalized"].fillna("") + " " +
        df.loc[mask_empty, "location"].fillna("") + " " +
        df.loc[mask_empty, "contract_type"].fillna("")
    ).str.strip()

    inserted = 0
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs_gold"))

        for _, row in df.iterrows():
            conn.execute(text("""
                INSERT INTO jobs_gold
                    (title_normalized, company, location, date_posted,
                     job_url, salary, contract_type, source, description_text)
                VALUES
                    (:title_normalized, :company, :location, :date_posted,
                     :job_url, :salary, :contract_type, :source, :description_text)
                ON DUPLICATE KEY UPDATE
                    description_text = VALUES(description_text)
            """), {
                "title_normalized": row["title_normalized"],
                "company":          str(row.get("company", "")),
                "location":         str(row.get("location", "")),
                "date_posted":      row.get("date_posted"),
                "job_url":          row["job_url"],
                "salary":           str(row.get("salary", "")),
                "contract_type":    str(row.get("contract_type", "")),
                "source":           str(row.get("source", "")),
                "description_text": row["description_text"],
            })
            inserted += 1

    log.info(f"[Gold] {inserted} enriched jobs written.")
    return inserted

# ── FULL PIPELINE ──────────────────────────────────────────────────────────────

def run_full_etl(jobs: list[dict]):
    log.info("=== ETL Pipeline Start ===")
    b = load_to_bronze(jobs)
    s = bronze_to_silver()
    g = silver_to_gold()
    log.info(f"=== ETL Done — Bronze:{b} Silver:{s} Gold:{g} ===")

def log_pipeline_run(
    run_id: str,
    task_name: str,
    status: str,
    jobs_scraped: int = 0,
    jobs_bronze: int = 0,
    jobs_silver: int = 0,
    jobs_gold: int = 0,
    duration_sec: int = 0,
    error_message: str = ""
):
    """Insert a pipeline run record into pipeline_logs."""
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO pipeline_logs
                    (run_id, task_name, status, jobs_scraped,
                     jobs_bronze, jobs_silver, jobs_gold,
                     duration_sec, error_message)
                VALUES
                    (:run_id, :task_name, :status, :jobs_scraped,
                     :jobs_bronze, :jobs_silver, :jobs_gold,
                     :duration_sec, :error_message)
            """), {
                "run_id":        run_id,
                "task_name":     task_name,
                "status":        status,
                "jobs_scraped":  jobs_scraped,
                "jobs_bronze":   jobs_bronze,
                "jobs_silver":   jobs_silver,
                "jobs_gold":     jobs_gold,
                "duration_sec":  duration_sec,
                "error_message": error_message,
            })
        log.info(f"[PipelineLog] Run logged — {task_name} | {status}")
    except Exception as e:
        log.error(f"[PipelineLog] Failed to log run: {e}")