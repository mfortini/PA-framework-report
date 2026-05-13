# Framework Census Pipeline

Pipeline per analizzare gli enti presenti in `enti.csv`, raccogliere i JavaScript caricati dalle homepage e inferire i framework o CMS usati.

## Stato attuale

Questo repository contiene:

- la struttura completa della pipeline;
- una pipeline completa separata in step rilanciabili;
- integrazione locale con `obscura`;
- raccolta dei JS via `obscura serve` e Playwright CDP.

## Prerequisiti

- Python 3.13+
- `uv`
- `obscura` disponibile nel `PATH` oppure in un percorso noto

## Installazione di `uv`

Se `uv` non e' installato:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verifica:

```bash
uv --version
```

## Setup progetto

Sincronizza l'ambiente Python locale:

```bash
make setup
```

In questo repository usiamo una cache `uv` locale in `.uv-cache/` per evitare dipendenze dal path cache globale.

## Installazione di `obscura`

Nel workspace puoi scaricarlo direttamente con:

```bash
make setup-obscura
```

In alternativa manualmente:

```bash
curl -LO https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-x86_64-linux.tar.gz
tar xzf obscura-x86_64-linux.tar.gz
chmod +x obscura obscura-worker
```

Poi:

```bash
export PATH="$PWD:$PATH"
```

Per default il `Makefile` passa `OBSCURA_BIN=$PWD/obscura` agli script.

Riferimento ufficiale:

- https://raw.githubusercontent.com/h4ckf0r0day/obscura/main/README.md

## Struttura

```text
scripts/
  common.py
  setup_obscura.py
  run_pipeline.py
  01_prepare_input.py
  02_probe_homepages.py
  03_collect_js_inventory.py
  04_download_js.py
  05_detect_frameworks.py
  06_build_reports.py
  07_build_web_report.py
data/
results/
results/js_files/
logs/
```

## Comandi principali

Run completa:

```bash
make run
```

Step singoli:

```bash
make prepare-input
make probe-homepages
make collect-js
make download-js
make detect-frameworks
make build-reports
make web-report
```

Pagina web dei risultati:

```bash
make web-report
```

Output:

```bash
results/report.html
```

Esecuzione diretta via `uv`:

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/01_prepare_input.py
UV_CACHE_DIR=.uv-cache uv run python scripts/run_pipeline.py
```

Debug e progresso:

```bash
UV_CACHE_DIR=.uv-cache OBSCURA_BIN=$PWD/obscura uv run python scripts/02_probe_homepages.py --limit 10 --progress-every 1 --debug
UV_CACHE_DIR=.uv-cache OBSCURA_BIN=$PWD/obscura uv run python scripts/03_collect_js_inventory.py --input results/homepages.jsonl --progress-every 1 --debug
UV_CACHE_DIR=.uv-cache uv run python scripts/04_download_js.py --progress-every 100 --debug
```

Resume e output incrementale:

- gli step lunghi scrivono progressivamente su file JSONL mentre lavorano
- puoi guardare i file crescere in `results/` durante l'esecuzione
- `02_probe_homepages.py`, `03_collect_js_inventory.py` e `04_download_js.py` usano `--resume` di default
- se rilanci lo stesso step sullo stesso file, le URL gia' processate vengono saltate
- se vuoi ricominciare da zero per uno step, usa `--no-resume`

Esempi:

```bash
UV_CACHE_DIR=.uv-cache OBSCURA_BIN=$PWD/obscura uv run python scripts/02_probe_homepages.py --resume
UV_CACHE_DIR=.uv-cache OBSCURA_BIN=$PWD/obscura uv run python scripts/03_collect_js_inventory.py --resume
UV_CACHE_DIR=.uv-cache uv run python scripts/04_download_js.py --resume
```

## Output attesi

- `data/enti_validi.csv`
- `data/enti_scartati.csv`
- `data/homepages_unique.csv`
- `results/homepages.jsonl`
- `results/homepages_html/`
- `results/js_inventory.jsonl`
- `results/css_inventory.jsonl`
- `results/js_downloads.jsonl`
- `results/framework_detection.jsonl`
- `results/summary.csv`
- `results/framework_summary.json`
- `results/report.html`

## Note operative

- `01_prepare_input.py` normalizza e valida le homepage.
- `02_probe_homepages.py` usa `obscura fetch` e salva anche uno snapshot HTML per homepage.
- `03_collect_js_inventory.py` usa `obscura fetch --eval` per estrarre script e stylesheet dal DOM e, quando disponibili, anche dalle Performance APIs della pagina.
- `04_download_js.py` scarica i JS via HTTP e li deduplica per `sha256`.
- `05_detect_frameworks.py` applica euristiche su URL, HTML, contenuti JS locali e CSS come segnale secondario per CMS e UI framework.
- `06_build_reports.py` produce un CSV finale per ente e un riepilogo aggregato.
- `07_build_web_report.py` genera una pagina web statica filtrabile per esplorare i risultati.

## Prossimi passi consigliati

1. eseguire `make setup`;
2. eseguire `make setup-obscura`;
3. fare una run pilota su un campione ristretto;
4. lanciare `make run`.
