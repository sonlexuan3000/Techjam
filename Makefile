PYTHON ?= python3
VENV_PYTHON := .venv/bin/python
UNSEEN_SEED ?= techjam-unseen-v1
UNSEEN_DIR := data/unseen_eval
ENTRYPOINT ?=

.PHONY: help setup data test demo submission-archive evaluate check unseen-data evaluate-unseen-dev \
	evaluate-candidate-dev evaluate-unseen-holdout human-stress stress benchmark \
	integration-check

help:
	@echo "make setup                    Create .venv and fetch the official catalog"
	@echo "make test                     Run fast unit/contract tests"
	@echo "make demo                     Run one deterministic multi-turn catalog demo"
	@echo "make submission-archive       Build a clean source-only submission zip"
	@echo "make evaluate                 Integration-only check on organizer public 200"
	@echo "make unseen-data              Reproduce shared 2,000 dev + 800 regression sessions"
	@echo "make evaluate-unseen-dev      Evaluate the generated shared dev split"
	@echo "make evaluate-candidate-dev   Evaluate ENTRYPOINT on generated shared dev"
	@echo "make evaluate-unseen-holdout  Evaluate the shared second split after freezing code"
	@echo "make human-stress             Run independent 100-case NLP benchmark"
	@echo "make stress                   Run wrapper stress on generated shared dev"
	@echo "make benchmark                Run candidate-safe checks (never public 200)"
	@echo "make integration-check        Run tests + public 200 after winners are frozen"

setup: $(VENV_PYTHON) data

$(VENV_PYTHON):
	$(PYTHON) -m venv .venv

data: $(VENV_PYTHON)
	$(VENV_PYTHON) scripts/bootstrap.py

test: $(VENV_PYTHON)
	$(VENV_PYTHON) -m unittest discover -v
	$(VENV_PYTHON) -m unittest discover \
		-s experiments/algo/tunglam-inverse-dp-review-prior/tests -v

demo: data
	$(VENV_PYTHON) scripts/demo_session.py --catalog data/catalog.jsonl

submission-archive:
	$(PYTHON) scripts/build_submission_archive.py

evaluate: data
	@test "$(PUBLIC_INTEGRATION)" = "1" || \
		(echo "Blocked: use generated tests for candidates; only run 'make integration-check' after winners are frozen."; exit 2)
	@echo "Running organizer public 200 as a frozen integration regression only."
	$(VENV_PYTHON) -m evaluator.local_evaluator

check: benchmark

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

evaluate-candidate-dev: unseen-data
	@test -n "$(ENTRYPOINT)" || \
		(echo "Set ENTRYPOINT=experiments/algo/<owner>-<approach>/entrypoint.py"; exit 2)
	$(VENV_PYTHON) scripts/evaluate_candidate.py \
		--entrypoint "$(ENTRYPOINT)" \
		--catalog data/catalog.jsonl \
		--dataset $(UNSEEN_DIR)/dev_set.jsonl \
		--output $(UNSEEN_DIR)/candidate_dev_results.json

evaluate-unseen-holdout: unseen-data
	$(VENV_PYTHON) -m evaluator.local_evaluator \
		--catalog data/catalog.jsonl \
		--dataset $(UNSEEN_DIR)/holdout_set.jsonl \
		--output $(UNSEEN_DIR)/holdout_results.json

human-stress: data
	$(VENV_PYTHON) scripts/evaluate_independent_paraphrases.py $(if $(strip $(ENTRYPOINT)),--entrypoint "$(ENTRYPOINT)",)

stress: unseen-data
	$(VENV_PYTHON) scripts/run_paraphrase_stress_eval.py \
		--catalog data/catalog.jsonl \
		--dataset $(UNSEEN_DIR)/dev_set.jsonl \
		--output $(UNSEEN_DIR)/dev_paraphrase_stress_results.json $(if $(strip $(ENTRYPOINT)),--entrypoint "$(ENTRYPOINT)",)

benchmark: test evaluate-unseen-dev human-stress

integration-check: test
	$(MAKE) PUBLIC_INTEGRATION=1 evaluate
