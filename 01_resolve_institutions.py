"""
Step 1 - SOURCE LAYER

Con questo script risolvo l'ID OpenAlex e il ROR di ciascuno dei 7 atenei
che confronto, usando l'endpoint /institutions, utilizzando un'API pubblica tramite api.key.

Salvo un dump raw completo (fino a 5 candidati per ricerca) per ogni
ateneo, per non perdere informazioni nel source layer.
Anche se poi in staging uso solo 3-4 campi, voglio poter tornare al dato
originale se scopro un problema più avanti.

IMPORTANTE: da qualche mese OpenAlex richiede una API key (il vecchio
parametro mailto/"polite pool" non basta più). L'ho scoperto strada facendo,
con un Error429 persistente che nessun backoff riusciva a risolvere - la causa
non era rate limiting, era proprio l'assenza della chiave. 

"""

import json
import os
import time
from pathlib import Path

import requests

MAILTO = "francesco.peraro@unibg.it"
API_KEY = os.environ.get("OPENALEX_API_KEY")

BASE_URL = "https://api.openalex.org/institutions"

# OpenAlex fa fuzzy match sul display_name, non serve il nome esatto.
UNIVERSITY_QUERIES = [
    "Università degli Studi di Bergamo",
    "Università degli Studi di Brescia",
    "Università degli Studi di Pavia",
    "Università degli Studi di Ferrara",
    "Università degli Studi di Modena e Reggio Emilia",
    "Università degli Studi di Trieste",
    "Università Ca Foscari Venezia",
]

RAW_DIR = Path(__file__).parent / "raw_institutions"
RAW_DIR.mkdir(exist_ok=True)


def resolve_institution(query: str) -> dict:
    """Chiamo /institutions?search=... e prendo il primo risultato.
    Salvo comunque il dump raw completo della risposta (fino a 5
    candidati), perché voglio poter controllare a mano se il match
    automatico ha preso l'istituzione sbagliata - mi è già capitato di
    dover verificare omonimie e sedi consorziate."""
    params = {"search": query, "per_page": 5, "mailto": MAILTO, "api_key": API_KEY}
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    safe_name = query.lower().replace(" ", "_").replace("'", "")
    with open(RAW_DIR / f"{safe_name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if not data.get("results"):
        return {"query": query, "matched": False}

    top = data["results"][0]
    return {
        "query": query,
        "matched": True,
        "openalex_id": top["id"],
        "display_name": top["display_name"],
        "ror": top.get("ror"),
        "country_code": top.get("country_code"),
        "works_count": top.get("works_count"),
        "cited_by_count": top.get("cited_by_count"),
        "homepage_url": top.get("homepage_url"),
    }


def main():
    results = []
    for q in UNIVERSITY_QUERIES:
        print(f"Risolvo: {q}")
        r = resolve_institution(q)
        results.append(r)
        # Con solo 7 chiamate non rischio nulla, ma metto comunque una
        # pausa minima per cortesia verso il servizio.
        time.sleep(0.5)

    out_path = Path(__file__).parent / "institutions_lookup.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nSalvato lookup in {out_path}")
    print("\n--- CONTROLLO A MANO OGNI RIGA PRIMA DI PROCEDERE ---")
    for r in results:
        if not r.get("matched"):
            print(f"  [NESSUN MATCH] {r['query']}")
        else:
            print(f"  {r['query']:55s} -> {r['display_name']:50s} ({r['openalex_id']})")


if __name__ == "__main__":
    main()
