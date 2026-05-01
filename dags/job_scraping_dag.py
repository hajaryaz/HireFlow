from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import time
import sys

sys.path.insert(0, "/opt/airflow/scrapers")
#from scraping_linkedin import scrape_linkedin_jobs
from scraping_france_travail import scrape_france_travail_jobs
from etl_pipeline import load_to_bronze, bronze_to_silver, silver_to_gold, log_pipeline_run

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

def extract_and_load(**context):
    run_id = context["run_id"]
    start  = time.time()
    try:
        ft_jobs  = scrape_france_travail_jobs()
        # li_jobs = scrape_linkedin_jobs()   
        all_jobs = ft_jobs  # + li_jobs

        count    = load_to_bronze(all_jobs)
        duration = int(time.time() - start)
        log_pipeline_run(
            run_id=run_id,
            task_name="extract_and_load_bronze",
            status="success",
            jobs_scraped=len(all_jobs),
            jobs_bronze=count,
            duration_sec=duration,
        )
        print(f"✅ Bronze loaded: {count} jobs in {duration}s")
    except Exception as e:
        log_pipeline_run(
            run_id=run_id,
            task_name="extract_and_load_bronze",
            status="failed",
            error_message=str(e),
            duration_sec=int(time.time() - start),
        )
        raise

def transform_silver(**context):
    run_id = context["run_id"]
    start  = time.time()
    try:
        count = bronze_to_silver()
        log_pipeline_run(
            run_id=run_id,
            task_name="transform_to_silver",
            status="success",
            jobs_silver=count,
            duration_sec=int(time.time() - start),
        )
        print(f"✅ Silver: {count} jobs")
    except Exception as e:
        log_pipeline_run(
            run_id=run_id,
            task_name="transform_to_silver",
            status="failed",
            error_message=str(e),
        )
        raise

def transform_gold(**context):
    run_id = context["run_id"]
    start  = time.time()
    try:
        count = silver_to_gold()
        log_pipeline_run(
            run_id=run_id,
            task_name="transform_to_gold",
            status="success",
            jobs_gold=count,
            duration_sec=int(time.time() - start),
        )
        print(f"✅ Gold: {count} jobs")
    except Exception as e:
        log_pipeline_run(
            run_id=run_id,
            task_name="transform_to_gold",
            status="failed",
            error_message=str(e),
        )
        raise

with DAG(
    dag_id="job_scraping_pipeline",
    default_args=default_args,
    description="Scrape LinkedIn + France Travail → ETL → MySQL",
    schedule_interval="0 7 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["jobs", "etl", "scraping"],
) as dag:

    t1 = PythonOperator(
        task_id="extract_and_load_bronze",
        python_callable=extract_and_load,
        provide_context=True,
    )
    t2 = PythonOperator(
        task_id="transform_to_silver",
        python_callable=transform_silver,
        provide_context=True,
    )
    t3 = PythonOperator(
        task_id="transform_to_gold",
        python_callable=transform_gold,
        provide_context=True,
    )

    t1 >> t2 >> t3