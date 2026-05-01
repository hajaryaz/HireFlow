"""
FastAPI Backend — Job Intelligent
Endpoints:
  GET  /jobs          → list jobs from Gold layer
  GET  /stats         → counts per source/title
  POST /match-cv      → upload CV text, get ranked job matches
  GET  /pipeline-logs → pipeline run history for monitoring
"""

import os
import logging
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import io
from datetime import datetime

# ── DB connection ──────────────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "mysql")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "job_intelligent")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASS = os.getenv("DB_PASS", "password")

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Job Intelligent API",
    description="Job search + CV matching API + Pipeline monitoring",
    version="1.0.0"
)

# Allow frontend to call the API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



def get_gold_jobs() -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM jobs_gold ORDER BY date_posted DESC", conn)
    return df

# ROUTES

@app.get("/")
def root():
    return {"status": "Job Intelligent API is running 🚀"}


@app.get("/jobs")
def list_jobs(
    title: str = Query(None, description="Filter by job title keyword"),
    location: str = Query(None, description="Filter by location"),
    source: str = Query(None, description="Filter by source (france_travail / linkedin)"),
    limit: int = Query(50, le=200),
    offset: int = Query(0)
):
    """Return jobs from the Gold layer with optional filters."""
    try:
        df = get_gold_jobs()

        if title:
            df = df[df["title_normalized"].str.contains(title, case=False, na=False)]
        if location:
            df = df[df["location"].str.contains(location, case=False, na=False)]
        if source:
            df = df[df["source"] == source]

        df = df.iloc[offset: offset + limit]
        df = df.fillna("")

        return {
            "total": len(df),
            "jobs": df.to_dict(orient="records")
        }
    except Exception as e:
        log.error(f"/jobs error: {e}")
        return {"error": str(e), "jobs": []}


@app.get("/stats")
def stats():
    """Return counts by title and source for dashboard."""
    try:
        df = get_gold_jobs()
        
        # By Title - with proper title names
        by_title = []
        title_counts = df["title_normalized"].value_counts().head(15)
        for title, count in title_counts.items():
            if title and title != "" and title != "Other":
                by_title.append({"title": title, "count": int(count)})
        
        # By Source - with proper source names
        by_source = []
        source_counts = df["source"].value_counts()
        for source, count in source_counts.items():
            if source and source != "":
                by_source.append({"source": source, "count": int(count)})
        
        # By Location - with proper location names
        by_location = []
        location_counts = df["location"].value_counts().head(10)
        for location, count in location_counts.items():
            if location and location != "":
                by_location.append({"location": location, "count": int(count)})
        
        return {
            "total_jobs": len(df),
            "by_title": by_title,
            "by_source": by_source,
            "by_location": by_location,
        }
    except Exception as e:
        log.error(f"/stats error: {e}")
        return {"error": str(e)}


@app.get("/pipeline-logs")
def pipeline_logs(limit: int = Query(50, description="Number of logs to return")):
    """Return pipeline run history for Power BI or dashboard."""
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                f"SELECT * FROM pipeline_logs ORDER BY executed_at DESC LIMIT {limit}",
                conn
            )
        df = df.fillna("")
        # Convert datetime to string for JSON serialization
        if "executed_at" in df.columns:
            df["executed_at"] = df["executed_at"].astype(str)
        
        return {
            "total_logs": len(df),
            "logs": df.to_dict(orient="records")
        }
    except Exception as e:
        log.error(f"/pipeline-logs error: {e}")
        return {"error": str(e), "logs": []}


@app.post("/match-cv")
async def match_cv(
    file: UploadFile = File(...),
    top_n: int = Query(10, description="Number of top matches to return")
):
    """
    Upload a CV as .txt or .pdf, get back ranked job matches using TF-IDF cosine similarity.
    """
    try:
        # Read the uploaded file
        content = await file.read()

        # Extract text
        if file.filename.endswith(".pdf"):
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(content))
                cv_text = " ".join(
                    page.extract_text() or "" for page in reader.pages
                )
            except Exception as e:
                return {"error": f"Could not read PDF: {e}"}
        else:
            # Treat as plain text
            cv_text = content.decode("utf-8", errors="ignore")

        if not cv_text.strip():
            return {"error": "CV appears to be empty or unreadable."}

        # Load Gold jobs
        df = get_gold_jobs()
        if df.empty:
            return {"error": "No jobs in database yet. Run the pipeline first."}

        df = df.fillna("")
        df["description_text"] = df["description_text"].str.strip()
        df = df[df["description_text"] != ""]

        if df.empty:
            return {"error": "No job descriptions available for matching."}

        # TF-IDF vectorization
        corpus = df["description_text"].tolist()
        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=5000,
            ngram_range=(1, 2)   # unigrams + bigrams for better matching
        )
        tfidf_matrix = vectorizer.fit_transform(corpus)
        cv_vector = vectorizer.transform([cv_text])

        # Cosine similarity
        scores = cosine_similarity(cv_vector, tfidf_matrix).flatten()
        df["match_score"] = scores
        df["match_score"] = (df["match_score"] * 100).round(1)  # convert to %

        # Return top N matches
        top = (
            df.sort_values("match_score", ascending=False)
            .head(top_n)[["title_normalized", "company", "location",
                           "job_url", "source", "match_score", "date_posted"]]
        )

        return {
            "cv_filename": file.filename,
            "total_jobs_compared": len(df),
            "top_matches": top.to_dict(orient="records")
        }

    except Exception as e:
        log.error(f"/match-cv error: {e}")
        return {"error": str(e)}