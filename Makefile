PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: venv install migrate superuser run

venv:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)

install: venv
	$(PIP) install -r requirements.txt

migrate: install
	$(PY) manage.py migrate

superuser: install
	$(PY) manage.py createsuperuser

run: migrate
	GO_API_BASE_URL=$${GO_API_BASE_URL:-http://localhost:8080/api} $(PY) manage.py runserver 0.0.0.0:8001

