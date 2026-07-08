"""
step 3 - SOURCE LAYER (scraping html, stesso portale per tutti gli atenei)

scraping leggero delle pagine profilo AlmaLaurea - laureati per anno, anno di fondazione, gruppi disciplinari coperti. 
mi serve per normalizzare il confronto sulla produzione scientifica per dimensione dell'ateneo invece che sui totali.

ho provato prima con USTAT MUR ma le pagine caricano tutto via JavaScript, quindi niente da fare con requests+BeautifulSoup senza
selenium (che per uno scraping che volevo leggero mi sembrava troppo). almaLaurea invece è html statico normale.

i 7 atenei riportano tutti lo stesso anno (2025) per i laureati, quindi il confronto è omogeneo.
"""

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    # Metto uno User-Agent: dichiaro cosa sono e perché...scrping etico :)
    "User-Agent": "UniBG-BI-BDA-homework-scraper/1.0 (uso accademico, contatto: francesco.peraro@unibg.it)"
}

# Ho verificato lo slug di Bergamo prima di lanciare lo scraping
# sugli altri 6 - gli altri li ho corretti dopo aver visto quali fallivano
# al primo tentativo.
ATENEI = {
    "Bergamo": "universita-degli-studi-di-bergamo",
    "Brescia": "universita-degli-studi-di-brescia",
    "Pavia": "universita-di-pavia",
    "Ferrara": "universita-degli-studi-di-ferrara",
    "Modena e Reggio Emilia": "universita-degli-studi-di-modena-e-reggio-emilia",
    "Trieste": "universita-degli-studi-di-trieste",
    "Ca Foscari Venezia": "universita-ca-foscari-venezia",
}

BASE_URL = "https://www.almalaurea.it/gli-atenei/{slug}"
RAW_DIR = Path(__file__).parent / "raw_almalaurea"
RAW_DIR.mkdir(exist_ok=True)


def scrape_ateneo(nome: str, slug: str) -> dict:
    url = BASE_URL.format(slug=slug)
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code != 404:
        # Salvo sempre l'HTML raw, anche se poi il parsing sotto fallisce:
        # mi serve per fare debug offline senza richiamare il sito di nuovo.
        (RAW_DIR / f"{slug}.html").write_text(resp.text, encoding="utf-8")

    if resp.status_code == 404:
        return {"ateneo": nome, "slug": slug, "ok": False, "errore": "404 not found"}

    soup = BeautifulSoup(resp.text, "html.parser")
    testo = soup.get_text(" ", strip=True)

    result = {"ateneo": nome, "slug": slug, "ok": True, "url": url}

    # Anno di fondazione: "istituzione statale fondata nel 1968"
    m = re.search(r"fondat[ao]\s+nel\s+(\d{4})", testo)
    result["anno_fondazione"] = int(m.group(1)) if m else None

    # Laureati totali: "i laureati sono 4.159"
    m = re.search(r"laureati\s+sono\s+([\d.]+)", testo)
    result["laureati_totali"] = int(m.group(1).replace(".", "")) if m else None

    # Split primo/secondo livello: "2.525 di primo livello e 1.634 di secondo livello"
    m = re.search(
        r"([\d.]+)\s+di\s+primo\s+livello\s+e\s+([\d.]+)\s+di\s+secondo\s+livello", testo
    )
    if m:
        result["laureati_primo_livello"] = int(m.group(1).replace(".", ""))
        result["laureati_secondo_livello"] = int(m.group(2).replace(".", ""))
    else:
        result["laureati_primo_livello"] = None
        result["laureati_secondo_livello"] = None

    # Gruppi disciplinari coperti: "10 gruppi disciplinari dei 15 complessivi"
    m = re.search(r"(\d+)\s+gruppi\s+disciplinari\s+dei\s+(\d+)\s+complessivi", testo)
    if m:
        result["gruppi_disciplinari_coperti"] = int(m.group(1))
        result["gruppi_disciplinari_totali"] = int(m.group(2))

    # Se non ho estratto nulla di utile, lo segnalo esplicitamente: vuol
    # dire che la pagina esiste ma il testo ha una struttura diversa da
    # quella che mi aspettavo da Bergamo, e devo controllarla a mano.
    campi_trovati = sum(
        1 for k in ("anno_fondazione", "laureati_totali") if result.get(k) is not None
    )
    if campi_trovati == 0:
        result["ok"] = False
        result["errore"] = "pagina trovata ma nessun campo atteso estratto - verifico a mano"

    return result


def main():
    results = []
    for nome, slug in ATENEI.items():
        print(f"Scraping: {nome} ({slug})")
        r = scrape_ateneo(nome, slug)
        results.append(r)
        if r["ok"]:
            print(f"  OK -> {r}")
        else:
            print(f"  FALLITO -> {r['errore']}")
        time.sleep(1.0)  # non ho bisogno di andare più veloce, resto cortese col server

    out_path = Path(__file__).parent / "almalaurea_lookup.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok = sum(1 for r in results if r["ok"])
    print(f"\n{n_ok}/{len(results)} atenei estratti correttamente. Dettagli in {out_path}")
    if n_ok < len(results):
        print("Per quelli falliti: apro l'URL nel browser, trovo lo slug corretto,")
        print("lo aggiorno nel dizionario ATENEI e rilancio solo per quelli.")


if __name__ == "__main__":
    main()
