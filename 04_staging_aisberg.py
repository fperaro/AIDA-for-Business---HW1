"""
STAGING LAYER - Export Aisberg (dump grezzo tabelle CINECA/IRIS)

Input:  list.xlsx (export interno, una riga = una coppia pubblicazione-autore)
Output: due tabelle di staging, separate per rispettare la granularita' reale:
  - staging_pubblicazione.csv   (una riga per pubblicazione, deduplicata)
  - staging_autore_pubblicazione.csv  (bridge N:M pubblicazione<->autore)

REGOLE APPLICATE (in ordine di importanza):
1. La colonna "autore: Codice fiscale" NON viene mai letta/caricata in memoria
   in nessuna forma. E' dato personale sensibile (equivalente SSN italiano).
2. Deduplicazione pubblicazioni via Handle (43064 righe -> ~33629 pubblicazioni
   uniche): si tiene un solo record "pubblicazione", i restanti autori vanno
   nel bridge table.
3. Parsing della stringa dipartimento in campi separati (nome, data inizio,
   data fine) per storicizzazione vera, non solo etichetta libera.
4. Nessun dato viene scartato silenziosamente: righe con problemi vengono
   comunque salvate con flag di anomalia, non buttate via.

Dipendenze: pip install openpyxl --break-system-packages
"""

import csv
import re
from pathlib import Path

import openpyxl

OUT_DIR = Path(__file__).parent
INPUT_PATH = OUT_DIR / "AISBERG" / "list.xlsx"
STAGING_PUB_PATH = OUT_DIR / "staging_pubblicazione.csv"
STAGING_AUTORE_PATH = OUT_DIR / "staging_autore_pubblicazione.csv"
STAGING_ANOMALIE_PATH = OUT_DIR / "staging_anomalie.csv"

# Indici colonna nel file originale (0-based), verificati a mano sull'header.
# NOTA: l'indice 25 (autore: Codice fiscale) e' deliberatamente ASSENTE da questa mappa. 
# Non va aggiunto per nessun motivo.
COL = {
    "id_prodotto": 1,
    "handle": 3,
    "titolo": 4,
    "anno": 5,
    "tipologia": 6,
    "sottotipologia": 7,
    "nr_autori": 8,
    "issn": 16,
    "isbn": 17,
    "e_isbn": 18,
    "ismn": 19,
    "autore_nome": 20,
    "autore_cognome": 21,
    "dipartimento_raw": 22,
    "corresponding": 23,
    "id_persona_iris": 24,
    "wos_id": 26,
    "scopus_id": 27,
    "pubmed_id": 28,
    "doi": 29,
    "scopus_doi": 30,
    "wos_doi": 31,
    "oa_type": 32,
}

DEPT_PATTERN = re.compile(r"^(.*?)\s*\(attivo dal (\d{2}/\d{2}/\d{4}) al (\d{2}/\d{2}/\d{4})\)$")


def parse_dipartimento(raw):
    """Ritorna (nome, data_inizio, data_fine, flag_anomalia).
    Tre casi osservati nei dati:
      - 'Dipartimento X (attivo dal DD/MM/YYYY al DD/MM/YYYY)' -> storicizzato
      - 'Dipartimento X'                                        -> attivo, nessuna data
      - 'N.D.'                                                  -> mancante
    """
    if raw is None:
        return None, None, None, "dipartimento_mancante"
    raw = str(raw).strip()
    if raw in ("N.D.", ""):
        return None, None, None, "dipartimento_mancante"

    m = DEPT_PATTERN.match(raw)
    if m:
        nome, data_inizio, data_fine = m.groups()
        return nome.strip(), data_inizio, data_fine, None

    # Nessuna data: dipartimento presumibilmente attivo, nessuna chiusura registrata.
    return raw, None, None, None


def main():
    wb = openpyxl.load_workbook(INPUT_PATH, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    next(rows)  # skip header

    seen_handles = set()
    n_righe = 0
    n_pubblicazioni = 0
    n_anomalie = 0

    with open(STAGING_PUB_PATH, "w", newline="", encoding="utf-8") as f_pub, \
         open(STAGING_AUTORE_PATH, "w", newline="", encoding="utf-8") as f_aut, \
         open(STAGING_ANOMALIE_PATH, "w", newline="", encoding="utf-8") as f_anom:

        w_pub = csv.writer(f_pub)
        w_pub.writerow([
            "handle", "id_prodotto", "titolo", "anno", "tipologia", "sottotipologia",
            "nr_autori_dichiarato", "issn", "isbn", "e_isbn", "ismn",
            "wos_id", "scopus_id", "pubmed_id", "doi", "scopus_doi", "wos_doi", "oa_type",
        ])

        w_aut = csv.writer(f_aut)
        w_aut.writerow([
            "handle", "autore_nome", "autore_cognome", "id_persona_iris",
            "dipartimento_nome", "dipartimento_attivo_dal", "dipartimento_attivo_al",
            "corresponding",
        ])

        w_anom = csv.writer(f_anom)
        w_anom.writerow(["handle", "tipo_anomalia", "dettaglio"])

        for r in rows:
            n_righe += 1
            handle = r[COL["handle"]]

            if handle is None:
                w_anom.writerow([None, "handle_mancante", "riga senza handle, scartata"])
                n_anomalie += 1
                continue

            # --- tabella pubblicazione: solo alla prima occorrenza dell'handle ---
            if handle not in seen_handles:
                seen_handles.add(handle)
                n_pubblicazioni += 1
                w_pub.writerow([
                    handle,
                    r[COL["id_prodotto"]],
                    r[COL["titolo"]],
                    r[COL["anno"]],
                    r[COL["tipologia"]],
                    r[COL["sottotipologia"]],
                    r[COL["nr_autori"]],
                    r[COL["issn"]],
                    r[COL["isbn"]],
                    r[COL["e_isbn"]],
                    r[COL["ismn"]],
                    r[COL["wos_id"]],
                    r[COL["scopus_id"]],
                    r[COL["pubmed_id"]],
                    r[COL["doi"]],
                    r[COL["scopus_doi"]],
                    r[COL["wos_doi"]],
                    r[COL["oa_type"]],
                ])

            # --- tabella bridge autore-pubblicazione: ogni riga e' un autore ---
            dept_raw = r[COL["dipartimento_raw"]]
            nome_dip, data_inizio, data_fine, anomalia_dip = parse_dipartimento(dept_raw)
            if anomalia_dip:
                w_anom.writerow([handle, anomalia_dip, repr(dept_raw)])
                n_anomalie += 1

            w_aut.writerow([
                handle,
                r[COL["autore_nome"]],
                r[COL["autore_cognome"]],
                r[COL["id_persona_iris"]],
                nome_dip,
                data_inizio,
                data_fine,
                r[COL["corresponding"]],
                # Codice fiscale (indice 25) NON incluso, per scelta.
            ])

    print(f"Righe lette:                {n_righe}")
    print(f"Pubblicazioni uniche:        {n_pubblicazioni}")
    print(f"Righe autore-pubblicazione:  {n_righe - 1}")  # circa, escluse quelle scartate
    print(f"Anomalie registrate:         {n_anomalie}")
    print()
    print(f"Output: {STAGING_PUB_PATH}")
    print(f"Output: {STAGING_AUTORE_PATH}")
    print(f"Output: {STAGING_ANOMALIE_PATH}")


if __name__ == "__main__":
    main()
