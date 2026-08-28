PYTHON ?= python3
VENV_PYTHON := .venv/bin/python
UNSEEN_SEED ?= techjam-unseen-v1
UNSEEN_DIR := data/unseen_eval

.PHONY: help setup data test evaluate check unseen-data evaluate-unseen-dev \
	evaluate-unseen-holdout stress benchmark

help:
	@echo "make setup                    Create .venv and fetch the official catalog"
	@echo "make test                     Run fast unit/contract tests"
	@echo "make evaluate                 Evaluate the public 200 sessions"
	@echo "make unseen-data              Reproduce shared 2,000 dev + 800 regression sessions"
	@echo "make evaluate-unseen-dev      Evaluate the generated shared dev split"
	@echo "make evaluate-unseen-holdout  Evaluate the shared second split after freezing code"
	@echo "make stress                   Run deterministic paraphrase stress evaluation"
	@echo "make benchmark                Run unit, public, unseen-dev, and stress checks"

setup: $(VENV_PYTHON) data

$(VENV_PYTHON):
	$(PYTHON) -m venv .venv

data: $(VENV_PYTHON)
	$(VENV_PYTHON) scripts/bootstrap.py

test: $(VENV_PYTHON)
	$(VENV_PYTHON) -m unittest discover -v

evaluate: data
	$(VENV_PYTHON) -m evaluator.local_evaluator

check: test evaluate

unseen-data: data
	@if [ -f "$(UNSEEN_DIR)/dev_set.jsonl" ] && \
		[ -f "$(UNSEEN_DIR)/holdout_set.jsonl" ] && \
		[ -f "$(UNSEEN_DIR)/manifest.json" ]; then \
		echo "Shared generated sessions already exist in $(UNSEEN_DIR)"; \
	else \
		$(VENV_PYTHON) scripts/build_unseen_official_sessions.py \
			--seed "$(UNSEEN_SEED)"; \
	fi

evaluate-unseen-dev: unseen-data
	$(VENV_PYTHON) -m evaluator.local_evaluator \
		--catalog data/catalog.jsonl \
		--dataset $(UNSEEN_DIR)/dev_set.jsonl \
		--output $(UNSEEN_DIR)/dev_results.json

evaluate-unseen-holdout: unseen-data
	$(VENV_PYTHON) -m evaluator.local_evaluator \
		--catalog data/catalog.jsonl \
		--dataset $(UNSEEN_DIR)/holdout_set.jsonl \
		--output $(UNSEEN_DIR)/holdout_results.json

stress: data
	$(VENV_PYTHON) scripts/run_paraphrase_stress_eval.py \
		--catalog data/catalog.jsonl \
		--dataset data/public_set.jsonl \
		--output $(UNSEEN_DIR)/public_paraphrase_stress_results.json

benchmark: test evaluate evaluate-unseen-dev stress
