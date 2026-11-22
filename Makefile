PY        ?= .venv/bin/python
RUN        = PYTHONPATH=evaluator $(PY) -m delusion_monitor
TARGET    ?= http://localhost:8000
STATE_DIR ?= .local-state

.PHONY: venv test validate check demo-case replay replay-alert local-up local-down local-grafana

venv:            ## Create .venv with evaluator + test dependencies
	python3 -m venv .venv && .venv/bin/pip install -q -r evaluator/requirements-dev.txt

test:            ## Unit + HTTP tests (no network, no API key)
	$(PY) -m pytest -q

validate:        ## terraform fmt/validate both stages (no AWS calls)
	terraform fmt -check -recursive infra
	terraform -chdir=infra/stage1-aws init -backend=false -input=false >/dev/null && terraform -chdir=infra/stage1-aws validate
	terraform -chdir=infra/stage2-grafana init -backend=false -input=false >/dev/null && terraform -chdir=infra/stage2-grafana validate
	bash -n scripts/*.sh

check: test validate  ## Everything that runs offline

demo-case:       ## Headline demo: "365 days." -> contradicted (exit 1 if not)
	$(RUN) evaluate --case prod-retention --response "365 days." --expect contradicted --target $(TARGET)

replay:          ## Replay the six canned cases against $(TARGET)
	$(RUN) replay --target $(TARGET)

replay-alert:    ## Replay the alert demo batch (12 evals, 75% flagged) against $(TARGET)
	$(RUN) replay --batch data/batches/alert-demo.json --target $(TARGET)

local-up:        ## Run evaluator + Prometheus + Grafana locally in one shared netns
	./scripts/local-up.sh

local-grafana:   ## Apply stage 2 to the LOCAL Grafana (state kept in $(STATE_DIR), not the AWS state)
	mkdir -p $(STATE_DIR)
	TF_VAR_grafana_admin_password=local-admin terraform -chdir=infra/stage2-grafana apply -auto-approve -input=false -state=$(abspath $(STATE_DIR))/stage2-local.tfstate

local-down:
	./scripts/local-down.sh
	rm -rf $(STATE_DIR)
