FROM apache/airflow:2.7.3-python3.11

USER root

RUN apt-get update && apt-get install -y \
    git \
    curl \
    && apt-get clean

USER airflow

COPY airflow/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m venv /home/airflow/dbt-venv \
    && PIP_USER=false /home/airflow/dbt-venv/bin/pip install --no-cache-dir --upgrade pip \
    && PIP_USER=false /home/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-bigquery==1.11.1"

WORKDIR /airflow