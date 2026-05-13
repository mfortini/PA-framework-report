# Piano di lavoro: censimento framework dai siti in `enti.csv`

## Obiettivo

Usare `obscura` per:

1. visitare gli enti presenti in `enti.csv`;
2. recuperare l'elenco dei file JavaScript caricati dalla homepage di ciascun ente;
3. salvare, quando utile, anche il contenuto dei JS scaricati;
4. determinare quali framework/librerie stanno usando.

Vincoli di implementazione richiesti:

1. la pipeline completa deve poter essere lanciata con uno script orchestratore;
2. ogni fase deve comunque esistere anche come script separato e lanciabile in autonomia;
3. deve esserci un `README.md` con istruzioni d'uso, prerequisiti e output attesi;
4. deve esserci un `Makefile` per lanciare l'intera pipeline o i singoli passi;
5. l'ambiente Python deve essere gestito con `uv`.

## Contesto verificato

- Nel workspace al momento è presente solo `enti.csv`.
- Il CSV contiene una colonna `Sito_istituzionale`.
- Alcuni siti nel CSV sono assenti o privi di schema (`www...` invece di `https://...`).
- `obscura` espone una CLI utile per:
  - `fetch` su singole URL;
  - `scrape` su più URL in parallelo;
  - `serve` come endpoint compatibile CDP per Playwright/Puppeteer.

## Assunzioni operative

- "Contattare tutti gli enti" significa almeno tentare la visita della homepage del `Sito_istituzionale` di ogni riga valida.
- L'analisi riguarda la homepage iniziale, non tutto il sito.
- Per "JS scaricati" ci interessa l'elenco delle risorse JavaScript effettivamente richieste dal browser durante il caricamento della homepage, non solo i tag `<script>` presenti nell'HTML.
- Dove il download del contenuto JS non riesce, registreremo comunque URL, hostname, status e motivo del fallimento.

## Strategia generale

La pipeline sarà in 2 livelli:

1. una passata di raccolta homepage e risorse JS;
2. una passata di classificazione framework basata su:
   - URL dei bundle;
   - nomi file;
   - contenuto dei JS;
   - marker nel DOM/HTML.

Poiché `obscura fetch --dump html/links` non basta da solo a ricostruire in modo affidabile tutte le richieste JS effettuate in pagina, useremo `obscura serve` come browser CDP e un piccolo client Playwright/Puppeteer per intercettare le richieste di rete della homepage.

## Fonti Di Riferimento E Benchmark

Per estendere il detector conviene mantenere una base rule-based interna, ma prendere spunto da fingerprint library e
workflow già consolidati.

Fonti da usare o consultare durante l'upgrade:

- Wappalyzer / Wappalyzer-Next come riferimento metodologico per fingerprint multi-sorgente
  (HTML, header, URL, global JS, meta tag, script pattern).
- BuiltWith come benchmark esterno per confronti spot sui casi dubbi e sui falsi negativi più evidenti.
- `cms-detector` di drateberry come riferimento focalizzato sui CMS e sui marker editoriali:
  https://github.com/drateberry/cms-detector/blob/main/cms_detector.py
- Guida di Pasquale Pillitteri su Wappalyzer e BuiltWith, utile per inquadrare bene limiti e differenze
  tra detection browser-side, server-side e verifica manuale:
  https://pasqualepillitteri.it/en/news/2424/how-to-detect-website-tech-stack-wappalyzer-builtwith

Principio operativo:

- non sostituire la pipeline attuale con un servizio esterno;
- usare queste fonti per ampliare il catalogo di firme, migliorare il ranking delle evidenze e definire un processo di validazione;
- conservare un output spiegabile, con evidenze esplicite per ogni classificazione.

## Output attesi

- `data/enti_validi.csv`
  - enti con URL normalizzata e pronta per la scansione
- `data/enti_scartati.csv`
  - righe senza sito o con URL non normalizzabile
- `results/homepages.jsonl`
  - un record per ente con esito visita homepage
- `results/js_inventory.jsonl`
  - una riga per ogni JS richiesto dalla homepage
- `results/js_files/`
  - contenuto dei JS scaricati, deduplicato per hash
- `results/framework_detection.jsonl`
  - evidenze e framework identificati per ente
- `results/summary.csv`
  - riepilogo finale per ente
- `README.md`
  - documentazione operativa della pipeline
- `Makefile`
  - entrypoint per run completa e step singoli
- `pyproject.toml`
  - configurazione progetto Python gestito con `uv`
- `uv.lock`
  - lockfile delle dipendenze Python

## Architettura esecutiva richiesta

La soluzione dovrà avere due livelli di esecuzione:

1. un orchestratore unico che lancia la pipeline end-to-end;
2. script indipendenti, uno per ciascuna fase principale.

Schema previsto:

- `scripts/run_pipeline.py`
  - orchestrazione completa
- `scripts/01_prepare_input.py`
  - lettura e normalizzazione di `enti.csv`
- `scripts/02_probe_homepages.py`
  - visita homepage e raccolta metadati iniziali
- `scripts/03_collect_js_inventory.py`
  - cattura dei JS caricati via CDP
- `scripts/04_download_js.py`
  - download e deduplica contenuti JS
- `scripts/05_detect_frameworks.py`
  - classificazione framework
- `scripts/06_build_reports.py`
  - produzione report finali

Ogni script dovrà:

- accettare argomenti CLI espliciti;
- leggere input da file prodotti dallo step precedente;
- scrivere output deterministici in percorsi noti;
- poter essere rilanciato senza dover rifare obbligatoriamente gli step già completati.

## Fase 1: bootstrap del workspace

1. Creare una struttura di lavoro:
   - `scripts/`
   - `data/`
   - `results/`
   - `results/js_files/`
   - `logs/`
2. Inizializzare il progetto Python con `uv`.
3. Definire dipendenze e comandi di esecuzione tramite `pyproject.toml`.
4. Installare o scaricare `obscura`.
5. Verificare la modalità di esecuzione scelta:
   - binario da release GitHub;
   - oppure build locale da sorgente.
6. Salvare versione e parametri usati in `logs/run_metadata.json`.
7. Creare `README.md` e `Makefile`.

## Fase 2: preparazione input da `enti.csv`

1. Leggere `enti.csv`.
2. Estrarre almeno:
   - `_id`
   - `Codice_IPA`
   - `Denominazione_ente`
   - `Sito_istituzionale`
3. Normalizzare gli URL:
   - aggiungere `https://` se manca lo schema;
   - fallback a `http://` solo se necessario;
   - rimuovere spazi e valori vuoti;
   - deduplicare gli URL identici.
4. Produrre:
   - `data/enti_validi.csv`
   - `data/enti_scartati.csv`

Implementazione:

- script dedicato: `scripts/01_prepare_input.py`
- invocazione tramite `uv run`

## Fase 3: raccolta homepage

Per ogni ente valido:

1. aprire la homepage con `obscura`;
2. attendere un caricamento robusto:
   - default: `domcontentloaded`
   - retry: `networkidle0`
   - timeout esplicito
3. registrare:
   - URL richiesta
   - URL finale dopo redirect
   - status generale visita
   - titolo pagina
   - eventuali errori
4. salvare un record in `results/homepages.jsonl`.

Nota:
`obscura scrape` è adatto per parallelizzare le visite, ma per inventariare i JS richiesti in modo affidabile servirà l'intercettazione degli eventi di rete via CDP.

Implementazione:

- script dedicato: `scripts/02_probe_homepages.py`
- invocazione tramite `uv run`

## Fase 4: inventario dei JavaScript caricati

Approccio previsto:

1. avviare `obscura serve` localmente;
2. connettere un client Playwright/Puppeteer al CDP;
3. per ogni homepage:
   - ascoltare tutte le response/request;
   - filtrare le risorse JavaScript per:
     - `resourceType`
     - `content-type`
     - estensione `.js`, `.mjs`
     - pattern `/_next/`, `/static/`, `/assets/`, ecc.
4. salvare per ogni risorsa:
   - ente
   - homepage
   - URL JS
   - hostname
   - status HTTP
   - content-type
   - dimensione se disponibile
   - eventuale redirect
   - ordine di caricamento

Output:

- `results/js_inventory.jsonl`

Implementazione:

- script dedicato: `scripts/03_collect_js_inventory.py`
- invocazione tramite `uv run`

## Fase 5: download opzionale del contenuto JS

Per ogni JS rilevato:

1. tentare il download del contenuto;
2. calcolare hash `sha256`;
3. deduplicare file identici;
4. salvare:
   - file fisico in `results/js_files/<sha256>.js`
   - metadati in `results/js_inventory.jsonl`

Regole:

- non riscaricare file con hash già noto;
- conservare anche JS di CDN, perché spesso contengono marker utili;
- opzionalmente limitare la dimensione massima scaricata per evitare bundle enormi.

Implementazione:

- script dedicato: `scripts/04_download_js.py`
- invocazione tramite `uv run`

## Fase 6: identificazione framework

La rilevazione framework userà più segnali.

### 6.1 Segnali da URL/nome file

- `wp-includes`, `wp-content` -> WordPress
- `_next/` -> Next.js
- `nuxt`, `/_nuxt/` -> Nuxt
- `webpack`, `runtime`, `chunk` -> ecosistema bundler SPA
- `elementor`, `woocommerce` -> plugin WordPress
- `drupal`, `sites/default/files/js` -> Drupal
- `joomla` -> Joomla
- `blazor` o `/_framework/` -> Blazor

### 6.2 Segnali da HTML/DOM

- `#__next` -> Next.js/React
- `#app`, `data-v-` -> Vue
- `ng-version` -> Angular
- `__NUXT__` -> Nuxt
- `wp-` class/meta/path -> WordPress
- `drupalSettings` -> Drupal

### 6.3 Segnali da contenuto JS

- stringhe o namespace come:
  - `React`
  - `Vue`
  - `Angular`
  - `webpackJsonp`
  - `__NEXT_DATA__`
  - `self.__next_f`
  - `window.__NUXT__`
  - `Drupal`
  - `jQuery`
  - `Bootstrap`
  - `Alpine`
  - `Svelte`
  - `Stimulus`

### 6.4 Modello di classificazione

Per ogni ente produrre:

- `framework_primario`
- `framework_secondari`
- `evidenze`
- `confidence` (`high` / `medium` / `low`)

Implementazione:

- script dedicato: `scripts/05_detect_frameworks.py`
- invocazione tramite `uv run`

## Piano Di Upgrade Sul Già Implementato

Stato attuale verificato nel repository:

- il detector esiste già in `scripts/05_detect_frameworks.py`;
- oggi usa marker statici su HTML, URL JS, contenuto JS scaricato e URL CSS;
- produce `framework_primario`, `framework_secondari`, `cms_primario`, `ui_frameworks`, `evidenze`, `confidence`;
- dai risultati correnti emergono forti volumi su `WordPress`, `React`, `jQuery` e `Bootstrap Italia`, quindi il problema non è più "avere un detector", ma ridurre rumore e aumentare precisione e copertura.

### Upgrade 1: rendere le regole più espressive

Obiettivo:

- passare da semplici tuple di marker a regole strutturate con peso, categoria e severità.

Interventi:

- trasformare `URL_RULES`, `HTML_RULES`, `CMS_RULES`, `CONTENT_RULES`, `CSS_URL_RULES` in un catalogo unico di fingerprint;
- per ogni fingerprint salvare:
  - tecnologia target
  - tipo sorgente (`html`, `url`, `content`, `css-url`, in seguito `headers`, `meta`, `script-inline`)
  - marker
  - peso
  - note
  - eventuale famiglia (`cms`, `framework`, `ui`, `analytics`, `hosting`)
- distinguere marker forti da marker deboli:
  - esempio: `__NEXT_DATA__` forte per Next.js
  - `createElement` debole per React, perché compare facilmente in bundle terzi
- introdurre una soglia minima diversa per tecnologia e per categoria.

Perché serve:

- oggi il ranking è quasi solo "quante volte compare un marker";
- questo favorisce librerie rumorose come `jQuery` e segnali generici come `createElement`.

### Upgrade 2: aggiungere nuove superfici di evidenza

Obiettivo:

- avvicinare la pipeline al modello Wappalyzer/BuiltWith, che incrocia più segnali pubblici.

Interventi:

- raccogliere e analizzare header HTTP della homepage e delle risorse principali;
- estrarre meta tag rilevanti (`generator`, `application-name`, `framework-specific`);
- analizzare script inline e variabili globali già presenti nell'HTML salvato;
- aggiungere pattern su path media/statici e naming conventions dei bundle;
- valutare la presenza di cookie o endpoint noti solo come segnale secondario, mai decisivo da solo.

Priorità pratica:

- partire da `meta generator`, header e script inline, perché sono ottenibili subito con gli artefatti già raccolti.

### Upgrade 3: rafforzare il ramo CMS

Obiettivo:

- migliorare la detection editoriale usando le fonti CMS-specifiche come `cms-detector`.

Interventi:

- ampliare i marker per WordPress, Drupal, Joomla e Liferay;
- introdurre firme per plugin/temi solo come evidenza subordinata al CMS principale;
- separare meglio il CMS dal framework runtime:
  - WordPress + React deve restare prima di tutto WordPress come CMS, con React come secondario;
- aggiungere un esito "CMS forte, framework applicativo non determinabile" invece di forzare un framework primario generico.

Effetto atteso:

- meno casi in cui `jQuery` o `React` scalzano una piattaforma editoriale che ha segnali più strutturali.

### Upgrade 4: scoring e decisione più robusti

Obiettivo:

- sostituire la scelta del primario basata solo sul conteggio con uno scoring spiegabile.

Interventi:

- calcolare uno score per tecnologia sommando pesi diversi per fonte:
  - `html` e `meta` ad alta affidabilità per CMS/SSR
  - `url` a media affidabilità
  - `content` utile ma da normalizzare per evitare duplicazioni da bundle ripetuti
  - `css-url` forte per UI framework, debole per framework applicativi
- deduplicare evidenze identiche per bundle, host o marker, per non gonfiare il punteggio;
- introdurre tie-break espliciti:
  - CMS strutturale prima di libreria generica
  - framework specifico prima di libreria trasversale
  - `Bootstrap Italia` prima di `Bootstrap`
- distinguere il concetto di:
  - `platform_primary`
  - `app_framework_primary`
  - `ui_frameworks`
  se il report finale ha bisogno di più granularità.

### Upgrade 5: riduzione dei falsi positivi

Obiettivo:

- abbassare il rumore osservabile soprattutto su `React`, `jQuery` e `Bootstrap`.

Interventi:

- depotenziare marker troppo generici come `createElement`, `bootstrap`, `Vue`;
- richiedere co-occorrenza di più segnali per alcune tecnologie:
  - es. `React` solo se insieme a `React`, `react.production`, root DOM nota, o pattern di bundle coerente;
- escludere evidenze provenienti da script terzi non rappresentativi del sito quando identificabili
  (widget, analytics, embed, marketing tools);
- introdurre una piccola blacklist di host notoriamente rumorosi.

### Upgrade 6: validazione continua e benchmark

Obiettivo:

- misurare se il detector migliora davvero.

Interventi:

- creare un dataset di validazione manuale di 100-200 siti rappresentativi;
- confrontare un campione con Wappalyzer/BuiltWith nei casi dubbi;
- salvare per ogni run:
  - top falsi positivi sospetti
  - top non rilevati
  - mismatch rispetto al benchmark manuale
- aggiungere nel report indicatori di qualità:
  - copertura
  - precisione stimata sul campione
  - quota di detection basate solo su evidenze deboli.

### Upgrade 7: evoluzione degli output

Obiettivo:

- far emergere meglio i limiti della classificazione, non solo il risultato finale.

Interventi:

- estendere `results/framework_detection.jsonl` con:
  - score per tecnologia
  - evidenze raggruppate per fonte
  - marker forti/deboli
  - eventuali esclusioni applicate
- aggiornare il report Observable per mostrare:
  - tecnologie con confidenza bassa ma CMS forte
  - distribuzione delle fonti di evidenza
  - siti "ibridi" CMS + framework client
  - casi sospetti da revisionare.

## Sequenza Consigliata Di Esecuzione

1. Rifattorizzare `scripts/05_detect_frameworks.py` verso un catalogo fingerprint unico e pesato.
2. Aggiungere meta tag, script inline e header come nuove fonti di evidenza.
3. Rafforzare il ramo CMS usando come riferimento anche `cms-detector`.
4. Introdurre scoring, deduplica delle evidenze e tie-break semantici.
5. Costruire un piccolo benchmark manuale e aggiornare il report con metriche di qualità.

Questa sequenza minimizza il rischio:

- i primi tre passi migliorano il motore senza cambiare la pipeline di raccolta;
- il benchmark arriva quando il detector è già abbastanza stabile da essere misurato in modo utile.

## Fase 7: reporting finale

Generare almeno due viste:

1. per ente:
   - anagrafica minima
   - homepage
   - framework identificati
   - numero JS caricati
   - note/errori
2. aggregata:
   - conteggio per framework
   - distribuzione per tipologia ente
   - top CDN / domini JS più frequenti

Implementazione:

- script dedicato: `scripts/06_build_reports.py`
- invocazione tramite `uv run`

## Tooling e developer experience

### Python con `uv`

Il progetto Python dovrà essere gestito con `uv`:

- dipendenze dichiarate in `pyproject.toml`;
- ambiente eseguibile con `uv run ...`;
- lockfile mantenuto in `uv.lock`;
- eventuali dipendenze di sviluppo installate sempre via `uv`.

### `README.md`

Il repository dovrà includere un `README.md` con:

- scopo del progetto;
- prerequisiti;
- installazione di `uv`;
- installazione o download di `obscura`;
- struttura delle cartelle;
- comandi per eseguire tutti gli step;
- esempio di run completa;
- descrizione degli output generati;
- note su limiti, timeout e retry.

### `Makefile`

Il `Makefile` dovrà esporre almeno:

- un target per il bootstrap;
- un target per la pipeline completa;
- un target per ogni step singolo;
- un target di pulizia output;
- un target di help.

Esempio di target attesi:

- `make setup`
- `make run`
- `make prepare-input`
- `make probe-homepages`
- `make collect-js`
- `make download-js`
- `make detect-frameworks`
- `make build-reports`
- `make clean`

## Robustezza e gestione errori

- Retry su timeout/transient network errors
- Redirect supportati
- Gestione TLS non perfetto dove possibile
- Distinzione chiara tra:
  - sito assente nel CSV
  - dominio non raggiungibile
  - homepage raggiunta ma senza JS
  - homepage con protezioni/bot block
  - homepage caricata ma framework non identificabile

## Aspetti di performance

- Partire con concorrenza bassa
- Aumentare solo dopo una prima run campione
- Cache locale dei JS già scaricati
- Deduplica per URL e per hash contenuto

## Aspetti etici e operativi

- Limitare la frequenza delle richieste
- Analizzare solo la homepage iniziale
- Evitare crawling profondo
- Valutare `--obey-robots` se scegliamo la modalità `serve` solo per homepage fetch e non per scraping massivo di sottopagine

## Sequenza di implementazione proposta

1. inizializzare il progetto Python con `uv` e predisporre la struttura base;
2. creare `README.md` e `Makefile`;
3. creare gli script separati per ogni fase;
4. creare lo script orchestratore della pipeline completa;
5. integrare `obscura serve` + Playwright/Puppeteer per catturare i JS;
6. eseguire una run pilota su un campione ristretto;
7. correggere i falsi positivi;
8. eseguire la run completa su tutti gli enti validi.

## Decisioni da fissare prima dell'esecuzione completa

1. usare solo l'elenco dei JS oppure scaricarne anche il contenuto;
2. usare il binario release di `obscura` oppure buildarlo da sorgente;
3. scegliere Playwright o Puppeteer come client CDP;
4. definire il numero massimo di enti da processare in parallelo.

## Risultato finale atteso

Una pipeline ripetibile che, partendo da `enti.csv`, produce un dataset finale per ente con:

- homepage effettivamente contattata;
- elenco dei JS caricati;
- eventuale archivio dei contenuti JS;
- framework/librerie identificati con evidenze e livello di confidenza.

La pipeline dovrà essere usabile sia:

- con un solo comando per la run completa;
- sia eseguendo manualmente i singoli step in modo indipendente tramite `uv run` e target `make`.
