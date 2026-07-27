PYTHON ?= python
NPM ?= npm
MV_HOST ?= 127.0.0.1
MV_PORT ?= 8000

.PHONY: validate-data test test-backend test-frontend build serve demo

validate-data:
	PYTHONPATH=backend $(PYTHON) scripts/validate_data.py

test: test-backend test-frontend

test-backend:
	PYTHONPATH=backend $(PYTHON) -m pytest backend/tests -q

test-frontend:
	cd frontend && $(NPM) test -- --run && $(NPM) run typecheck

build:
	cd frontend && $(NPM) run build

serve:
	$(PYTHON) scripts/serve.py --host $(MV_HOST) --port $(MV_PORT)

demo:
	$(PYTHON) scripts/record_demo.py
