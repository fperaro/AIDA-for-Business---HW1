"""
STAGING LAYER - openalex (i 7 atenei del confronto)

tengo questo staging snello: i record openalex hanno campi pesanti (abstract, referenced_works, concepts, mesh, counts_by_year...) 
che non mi servono per il confronto che ho impostato. 
con 184.887 record e 5,25GB totali non ha senso portarmeli dietro fino al Data Warehouse.

a differenza di Aisberg qui non faccio una tabella ponte autori - mi basta un record per pubblicazione, 
il dettaglio per autore ce l'ho già (più ricco) su Bergamo via Aisberg.

Input:  raw_works/<ateneo>.jsonl  (uno per ciascuno dei 7 atenei)
Output: staging_openalex.csv      (un file unico, con colonna ateneo)
"""

import csv
import json
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw_works"
OUT_PATH = Path(__file__).parent / "staging_openalex.csv"

# Ricostruisco il nome leggibile dell'ateneo dal nome del file, che a sua
# volta arriva dal display_name OpenAlex passato attraverso lo slug usato
# nello script di harvest (lower + underscore). Lo faccio a mano una volta,
# invece di riderivarlo con una regex fragile.
ATENEO_DA_FILE = {
    "university_of_bergamo.jsonl": "Bergamo",
    "university_of_brescia.jsonl": "Brescia",
    "university_of_pavia.jsonl": "Pavia",
    "university_of_ferrara.jsonl": "Ferrara",
    "university_of_modena_and_reggio_emilia.jsonl": "Modena e Reggio Emilia",
    "university_of_trieste.jsonl": "Trieste",
    "ca'_foscari_university_of_venice.jsonl": "Ca' Foscari Venezia",
}

CAMPI_OUTPUT = [
    "ateneo", "openalex_id", "doi", "title", "anno", "data_pubblicazione",
    "lingua", "tipo", "is_retracted",
    "is_oa", "oa_status",
    "topic_nome", "subfield", "field", "domain", "topic_score",
    "venue_nome", "venue_tipo",
    "n_autori", "n_istituzioni_distinte", "n_paesi_distinti",
]


def estrai_riga(record, ateneo):
    """Prendo solo i campi che mi servono, con .get() ovunque perche' non
    tutti i record hanno tutti i campi popolati (es. primary_topic puo'
    mancare per record molto vecchi o poco indicizzati)."""
    primary_topic = record.get("primary_topic") or {}
    subfield = primary_topic.get("subfield") or {}
    field = primary_topic.get("field") or {}
    domain = primary_topic.get("domain") or {}

    primary_location = record.get("primary_location") or {}
    source = primary_location.get("source") or {}

    open_access = record.get("open_access") or {}

    return {
        "ateneo": ateneo,
        "openalex_id": record.get("id"),
        "doi": record.get("doi"),
        "title": record.get("title"),
        "anno": record.get("publication_year"),
        "data_pubblicazione": record.get("publication_date"),
        "lingua": record.get("language"),
        "tipo": record.get("type"),
        "is_retracted": record.get("is_retracted"),
        "is_oa": open_access.get("is_oa"),
        "oa_status": open_access.get("oa_status"),
        "topic_nome": primary_topic.get("display_name"),
        "subfield": subfield.get("display_name"),
        "field": field.get("display_name"),
        "domain": domain.get("display_name"),
        "topic_score": primary_topic.get("score"),
        "venue_nome": source.get("display_name"),
        "venue_tipo": source.get("type"),
        "n_autori": len(record.get("authorships") or []),
        "n_istituzioni_distinte": record.get("institutions_distinct_count"),
        "n_paesi_distinti": record.get("countries_distinct_count"),
    }


def main():
    n_totale = 0
    n_senza_topic = 0

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=CAMPI_OUTPUT)
        writer.writeheader()

        for file_raw, ateneo in ATENEO_DA_FILE.items():
            path = RAW_DIR / file_raw
            if not path.exists():
                print(f"ATTENZIONE: non trovo {path}, salto {ateneo}")
                continue

            n_ateneo = 0
            # Leggo riga per riga, non carico il file intero in memoria:
            # con file da centinaia di MB / oltre 1GB non ha senso fare
            # altrimenti.
            with open(path, encoding="utf-8") as f_in:
                for riga in f_in:
                    riga = riga.strip()
                    if not riga:
                        continue
                    record = json.loads(riga)
                    riga_out = estrai_riga(record, ateneo)
                    if riga_out["domain"] is None:
                        n_senza_topic += 1
                    writer.writerow(riga_out)
                    n_ateneo += 1
                    n_totale += 1

            print(f"{ateneo:30s} {n_ateneo:>7d} record")

    print()
    print(f"Totale record scritti in staging: {n_totale}")
    print(f"Record senza primary_topic (domain mancante): {n_senza_topic}")
    print(f"Output: {OUT_PATH}")


if __name__ == "__main__":
    main()
