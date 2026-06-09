# SynthMK — make targets for validate / install / package.
# Plain Python + shell; no build/compile step.

PYTHON ?= python3
SYNTHMK_HOME ?= /opt/synthmk

.PHONY: help ci validate validate-contract validate-export install uninstall package clean

help:
	@echo "SynthMK targets:"
	@echo "  make ci                full release contract (validate + syntax + determinism + secrets + version)"
	@echo "  make validate          contract test + recorder-export contract check"
	@echo "  make validate-contract browser-free runner output-contract test only"
	@echo "  make validate-export   recorder YAML -> runner contract (needs node)"
	@echo "  make install           install to \$$SYNTHMK_HOME + agent local dir (root)"
	@echo "  make uninstall         remove install"
	@echo "  make package           build dist/synthmk-<version>.mkp skeleton"
	@echo "  make clean             remove dist/ and caches"

# The single contract GitHub Actions and future agents both run. Superset of
# `validate`: adds shell/JS syntax, byte-identical package rebuild, a tracked-file
# secret scan, and VERSION<->package<->docs consistency. See scripts/ci.sh.
ci:
	bash scripts/ci.sh

# Single command that proves the whole loop without a browser:
#  1. runner output contract (Checkmk line shape, escalation, assertions, env subst)
#  2. recorder-exported YAML is consumable by the runner's own load_flow contract
validate: validate-contract validate-export
	@echo "VALIDATE OK"

validate-contract:
	$(PYTHON) runner/test_contract.py

validate-export:
	bash extension/validate_export.sh

install:
	bash install.sh

uninstall:
	bash install.sh --uninstall

package:
	bash packaging/build_mkp.sh

clean:
	rm -rf dist
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .ruff_cache
