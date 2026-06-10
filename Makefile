# SynthMK — make targets for validate / install / package.
# Plain Python + shell; no build/compile step.

PYTHON ?= python3
SYNTHMK_HOME ?= /opt/synthmk

FLOWS := $(wildcard flows/*.yaml) $(wildcard lab/flows/*.yaml)

.PHONY: help ci validate validate-contract validate-export lint-flows package package-contract real-mkp runner-image lab-up lab-down install uninstall clean

help:
	@echo "SynthMK targets:"
	@echo "  make ci                full release contract (validate + syntax + determinism + secrets + version)"
	@echo "  make validate          contract test + flow lint + recorder-export contract check"
	@echo "  make validate-contract browser-free runner output-contract test only"
	@echo "  make validate-export   recorder YAML -> runner contract (needs node)"
	@echo "  make lint-flows        static schema lint of flows/*.yaml (browser-free)"
	@echo "  make install           install to \$$SYNTHMK_HOME + agent local dir (root)"
	@echo "  make uninstall         remove install"
	@echo "  make package           build dist/synthmk-<version>.mkp skeleton (deterministic)"
	@echo "  make package-contract  assert built MKP payload has expected files/paths"
	@echo "  make real-mkp          build a REAL installable .mkp via a running Checkmk site"
	@echo "  make runner-image      build the runner-node Docker image (synthmk-runner)"
	@echo "  make lab-up / lab-down bring the LAN lab (Checkmk + runner + demo) up / down"
	@echo "  make clean             remove dist/ and caches"

# The single contract GitHub Actions and future agents both run. Superset of
# `validate`: adds shell/JS syntax, byte-identical package rebuild, a tracked-file
# secret scan, and VERSION<->package<->docs consistency. See scripts/ci.sh.
ci:
	bash scripts/ci.sh

# Single command that proves the whole loop without a browser:
#  1. runner output contract (Checkmk line shape, escalation, assertions, env subst)
#  2. static flow lint (every flows/*.yaml is schema-valid for the runner)
#  3. recorder-exported YAML is consumable by the runner's own load_flow contract
validate: validate-contract validate-import validate-admin lint-flows validate-export
	@echo "VALIDATE OK"

validate-admin:
	$(PYTHON) runner-node/test_admin_contract.py

validate-contract:
	$(PYTHON) runner/test_contract.py

validate-import:
	$(PYTHON) runner/test_import_devtools.py

lint-flows:
	$(PYTHON) runner/flow_lint.py $(FLOWS)

validate-export:
	bash extension/validate_export.sh

install:
	bash install.sh

uninstall:
	bash install.sh --uninstall

package:
	bash packaging/build_mkp.sh

package-contract:
	$(PYTHON) packaging/test_package_contract.py

# Real, installable MKP via a running Checkmk site's own mkp tool (needs the lab
# Checkmk container up: `make lab-up` or `cd lab && docker compose up -d checkmk`).
real-mkp:
	bash packaging/make_real_mkp.sh

# Runner-node appliance + LAN lab (Docker). Not part of `make ci` (needs Docker).
runner-image:
	docker build -f runner-node/Dockerfile -t synthmk-runner:$(shell cat VERSION) .

# Screenshot links must be clickable from OTHER machines on the LAN, so the
# default base URL is this host's primary IP (override with
# SYNTHMK_SHOT_BASE_URL=http://name:9180 make lab-up).
lab-up:
	cd lab && SYNTHMK_SHOT_BASE_URL="$${SYNTHMK_SHOT_BASE_URL:-http://$$(hostname -I | awk '{print $$1}'):9180}" \
		docker compose up -d --build

lab-down:
	cd lab && docker compose down -v

clean:
	rm -rf dist
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .ruff_cache
