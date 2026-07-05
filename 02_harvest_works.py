"""
Step 2 - SOURCE LAYER

Con questo script scarico in blocco le pubblicazioni di ciascuno
dei 7 atenei, usando l'ID OpenAlex risolto nello step 1. Uso la cursor
pagination perché con più di 10.000 record - 7 atenei su 10 anni, alcuni con area medica;
è l'unico modo che OpenAlex mette a disposizione per estrarre tutto senza troncamenti.

Salvo un file JSONL raw per ateneo: un work per riga, JSON completo così
come arriva dall'API. Non faccio nessun parsing/pulizia qui - quello lo
faccio nello staging. Il source layer non deve mai perdere informazione.

Uso: python 02_harvest_works.py                                     -> harvesting
     python 02_harvest_works.py campione raw_works/<file>.jsonl     -> stampa un campione

"""

import json
import os
import sys
import time
from pathlib import Path

import requests

MAILTO = "francesco.peraro@unibg.it"
API_KEY = os.environ.get("OPENALEX_API_KEY")
BASE_URL = "https://api.openalex.org/works"

# Range temporale: lo alzo o abbasso per gestire la cardinalità. Con i 7
# atenei del confronto (alcuni con area medica) sono arrivato a quasi
# 185.000 record su 10 anni - gestibile, ma se dovessi allargare ancora
# il taglio più semplice resta questo, non il numero di atenei.
FROM_YEAR = 2015
TO_YEAR = 2025

RAW_DIR = Path(__file__).parent / "raw_works"
RAW_DIR.mkdir(exist_ok=True)

RETRYABLE_STATUS = {500, 502, 503, 504}
MAX_RETRIES = 6
MAX_RETRIES_429 = 10           # il 429 prolungato lo tratto diversamente,
                               # mi ci sono scontrato ed è un caso diverso
BASE_DELAY_429 = 15
PACING_DELAY = 0.15            # pausa proattiva tra richieste riuscite,
                               # per non sfiorare il rate limit di burst


def _get_with_retry(params):
    """GET con backoff esponenziale su errori transitori.
    Tengo il 429 separato dagli altri 5xx/errori di rete: mi sono accorto
    sul campo che un 429 prolungato ha bisogno di un raffreddamento più
    lungo, non bastano pochi secondi in più a ogni tentativo."""
    delay = 3
    delay_429 = BASE_DELAY_429
    attempt = 0
    attempt_429 = 0

    while True:
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
        except requests.exceptions.RequestException as e:
            attempt += 1
            if attempt == MAX_RETRIES:
                raise
            print(f"  Errore di rete ({e}), tentativo {attempt}/{MAX_RETRIES}, attendo {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue

        if resp.status_code == 429:
            attempt_429 += 1
            if attempt_429 == MAX_RETRIES_429:
                resp.raise_for_status()
            print(f"  Rate limited (429), tentativo {attempt_429}/{MAX_RETRIES_429}, attendo {delay_429}s...")
            time.sleep(delay_429)
            delay_429 = min(delay_429 * 1.5, 120)
            continue

        if resp.status_code in RETRYABLE_STATUS:
            attempt += 1
            if attempt == MAX_RETRIES:
                resp.raise_for_status()
            print(f"  HTTP {resp.status_code}, tentativo {attempt}/{MAX_RETRIES}, attendo {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue

        resp.raise_for_status()
        time.sleep(PACING_DELAY)
        return resp


def load_institutions() -> list[dict]:
    lookup_path = Path(__file__).parent / "institutions_lookup.jsonl"
    institutions = []
    with open(lookup_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("matched"):
                institutions.append(rec)
    return institutions


def harvest_institution(institution: dict) -> int:
    """Cursor pagination su /works filtrato per institutions.id.

    Uso un checkpoint (il cursore corrente salvato su disco dopo ogni
    pagina) perché mi è già capitato che lo script si interrompesse a
    metà - senza checkpoint, ripartire voleva dire perdere tutto il
    lavoro fatto fino a quel punto su quell'ateneo. Distinguo anche
    "non ancora iniziato" da "già completato con successo": mi è
    capitato di sovrascrivere per errore un file già completo, perché
    a fine harvesting rimuovo il checkpoint (giustamente), ma un
    rilancio successivo lo interpretava come "non ancora iniziato"."""
    openalex_id = institution["openalex_id"].split("/")[-1]
    safe_name = institution["display_name"].lower().replace(" ", "_")
    out_path = RAW_DIR / f"{safe_name}.jsonl"
    checkpoint_path = RAW_DIR / f"{safe_name}.cursor"

    filter_str = (
        f"institutions.id:{openalex_id},"
        f"publication_year:{FROM_YEAR}-{TO_YEAR}"
    )

    if checkpoint_path.exists():
        cursor = checkpoint_path.read_text().strip()
        n_downloaded = sum(1 for _ in open(out_path, encoding="utf-8")) if out_path.exists() else 0
        print(f"  Riprendo da checkpoint: {n_downloaded} record già salvati")
        file_mode = "a"
    elif out_path.exists() and out_path.stat().st_size > 0:
        # Nessun checkpoint ma il file ha già contenuto: l'ho già
        # completato in una run precedente. Non lo sovrascrivo.
        n_downloaded = sum(1 for _ in open(out_path, encoding="utf-8"))
        print(f"  Già completato in precedenza: {n_downloaded} record. Salto.")
        return n_downloaded
    else:
        cursor = "*"
        n_downloaded = 0
        file_mode = "w"

    params = {
        "filter": filter_str,
        "per_page": 200,
        "cursor": cursor,
        "mailto": MAILTO,
        "api_key": API_KEY,
    }

    with open(out_path, file_mode, encoding="utf-8") as out_f:
        while True:
            resp = _get_with_retry(params)
            data = resp.json()

            for work in data["results"]:
                out_f.write(json.dumps(work, ensure_ascii=False) + "\n")
                n_downloaded += 1
            out_f.flush()  # scrivo su disco a ogni pagina, non solo a fine ciclo

            next_cursor = data["meta"].get("next_cursor")
            if not next_cursor:
                checkpoint_path.unlink(missing_ok=True)  # completato, rimuovo il checkpoint
                break

            params["cursor"] = next_cursor
            checkpoint_path.write_text(next_cursor)

            if n_downloaded % 1000 == 0:
                print(f"  {institution['display_name']}: {n_downloaded} record...")

    return n_downloaded


def run_harvest():
    institutions = load_institutions()
    if not institutions:
        print("Nessun ateneo risolto trovato. Eseguo prima 01_resolve_institutions.py")
        return

    summary = {}
    for inst in institutions:
        print(f"\nHarvest: {inst['display_name']} ({inst['openalex_id']})")
        count = harvest_institution(inst)
        summary[inst["display_name"]] = count
        print(f"  -> {count} record salvati")

    print("\n--- RIEPILOGO ---")
    for name, count in summary.items():
        print(f"  {name:55s}: {count:6d} pubblicazioni ({FROM_YEAR}-{TO_YEAR})")

    total = sum(summary.values())
    print(f"\n  TOTALE: {total} record")
    if total > 150_000:
        print("  Cardinalità alta - non torno indietro a restringere gli anni ora che")
        print("  l'harvesting è fatto, ma ne terrò conto in staging (scarto i campi")
        print("  pesanti che non uso, non porto tutto fino al Data Warehouse).")


def mostra_campione(path: str):
    """Aggiungo questa modalità perché mi serve spesso controllare al volo
    la struttura reale di un record - specialmente campi annidati come
    primary_topic, che uso per il confronto per area disciplinare. Leggo
    solo la prima riga, non tutto il file: con file da centinaia di MB
    non ha senso caricarli interi solo per guardare un record."""
    with open(path, encoding="utf-8") as f:
        riga = f.readline()
    record = json.loads(riga)

    print("--- CHIAVI DI PRIMO LIVELLO DISPONIBILI ---")
    print(list(record.keys()))
    print()
    print("--- primary_topic ---")
    print(json.dumps(record.get("primary_topic"), indent=2, ensure_ascii=False))
    print()
    print("--- topics (primi 2, se presente) ---")
    print(json.dumps(record.get("topics", [])[:2], indent=2, ensure_ascii=False))
    print()
    print("--- cited_by_count ---")
    print(record.get("cited_by_count"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "campione":
        if len(sys.argv) < 3:
            print("Uso: python 02_harvest_works.py campione raw_works/<file>.jsonl")
        else:
            mostra_campione(sys.argv[2])
    else:
        run_harvest()
