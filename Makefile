.PHONY: setup data pipeline all test lint dashboard clean

PY ?= python

setup:            ## install dependencies
	$(PY) -m pip install -r requirements.txt

data:             ## regenerate the synthetic raw CSVs
	$(PY) -m src.generate_data

pipeline:         ## run bronze -> silver -> gold -> data quality (generates data if missing)
	$(PY) -m src.pipeline

all:              ## fresh data + full pipeline
	$(PY) -m src.pipeline --regenerate

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

dashboard:        ## open the Streamlit dashboard on http://localhost:8501
	$(PY) -m streamlit run dashboard/app.py

clean:
	rm -rf data/raw warehouse .pytest_cache .ruff_cache
