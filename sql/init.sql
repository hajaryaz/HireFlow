CREATE DATABASE IF NOT EXISTS job_intelligent;
USE job_intelligent;

-- BRONZE: raw data exactly as scraped
CREATE TABLE IF NOT EXISTS jobs_bronze (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    title            VARCHAR(255),
    company          VARCHAR(255),
    location         VARCHAR(255),
    date_posted      VARCHAR(50),
    job_url          VARCHAR(500),
    search_keyword   VARCHAR(100),
    scraped_at       VARCHAR(50),
    salary           VARCHAR(255),
    contract_type    VARCHAR(100),
    source           VARCHAR(50),
    ingested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SILVER: cleaned and deduplicated
CREATE TABLE IF NOT EXISTS jobs_silver (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    title_normalized VARCHAR(100),
    company          VARCHAR(255),
    location         VARCHAR(255),
    date_posted      DATE,
    job_url          VARCHAR(500) UNIQUE,
    salary           VARCHAR(255),
    contract_type    VARCHAR(100),
    source           VARCHAR(50),
    processed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- GOLD: enriched, NLP-ready
CREATE TABLE IF NOT EXISTS jobs_gold (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    title_normalized VARCHAR(100),
    company          VARCHAR(255),
    location         VARCHAR(255),
    date_posted      DATE,
    job_url          VARCHAR(500) UNIQUE,
    salary           VARCHAR(255),
    contract_type    VARCHAR(100),
    source           VARCHAR(50),
    description_text TEXT,
    enriched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    run_id         VARCHAR(200),
    task_name      VARCHAR(100),
    status         VARCHAR(20),
    jobs_scraped   INT DEFAULT 0,
    jobs_bronze    INT DEFAULT 0,
    jobs_silver    INT DEFAULT 0,
    jobs_gold      INT DEFAULT 0,
    duration_sec   INT DEFAULT 0,
    error_message  TEXT,
    executed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);