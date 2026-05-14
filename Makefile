UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
OBSCURA_BIN ?= $(CURDIR)/obscura
UV_RUN = UV_CACHE_DIR=$(UV_CACHE_DIR) OBSCURA_BIN=$(OBSCURA_BIN) uv run

.PHONY: help setup setup-obscura run prepare-input probe-homepages enrich-headers collect-js download-js detect-frameworks build-reports web-report clean

help:
	@printf '%s\n' \
		'make setup              - crea/sincronizza l ambiente uv' \
		'make setup-obscura      - scarica obscura nel workspace' \
		'make run                - esegue la pipeline completa' \
		'make prepare-input      - normalizza enti.csv' \
		'make probe-homepages    - visita le homepage' \
		'make enrich-headers     - arricchisce homepages.jsonl con header HTTP e cookie' \
		'make collect-js         - raccoglie i JS esterni' \
		'make download-js        - scarica i JS rilevati' \
		'make detect-frameworks  - inferisce i framework' \
		'make build-reports      - genera report finali' \
		'make web-report         - genera la pagina web statica' \
		'make clean              - pulisce output generati'

setup:
	mkdir -p .uv-cache
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync

setup-obscura:
	$(UV_RUN) python scripts/setup_obscura.py

run:
	$(UV_RUN) python scripts/run_pipeline.py

prepare-input:
	$(UV_RUN) python scripts/01_prepare_input.py

probe-homepages:
	$(UV_RUN) python scripts/02_probe_homepages.py

enrich-headers:
	$(UV_RUN) python scripts/02_probe_homepages.py --headers-only --output results/homepages.jsonl

collect-js:
	$(UV_RUN) python scripts/03_collect_js_inventory.py

download-js:
	$(UV_RUN) python scripts/04_download_js.py

detect-frameworks:
	$(UV_RUN) python scripts/05_detect_frameworks.py

build-reports:
	$(UV_RUN) python scripts/06_build_reports.py

web-report:
	$(UV_RUN) python scripts/07_build_web_report.py

clean:
	rm -f data/enti_validi.csv data/enti_scartati.csv data/homepages_unique.csv
	rm -f results/homepages.jsonl results/js_inventory.jsonl results/css_inventory.jsonl results/js_downloads.jsonl results/framework_detection.jsonl results/summary.csv results/framework_summary.json results/report.html
	rm -rf results/homepages_html
