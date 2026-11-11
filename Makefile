.PHONY: install run test lint e2e evals deploy teardown

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

run:
	./scripts/run_local.sh

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/ruff check app tests scripts evals && .venv/bin/ruff format --check app tests scripts evals

# Talks to a running server with synthesised seller speech (needs Vertex AI access).
e2e:
	.venv/bin/python scripts/e2e_voice_test.py --url $${URL:-ws://localhost:8080/ws/call}

# Simulated-seller conversations scored by an LLM judge (needs Vertex AI access).
evals:
	.venv/bin/python -m evals.run_evals

deploy:
	./scripts/deploy.sh

teardown:
	./scripts/teardown.sh
