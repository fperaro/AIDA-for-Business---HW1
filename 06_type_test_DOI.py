import json
from collections import Counter

path = "raw_works/university_of_bergamo.jsonl"  # aggiusta il percorso se serve

tipo_count = Counter()
n_tot = 0
with open(path, encoding="utf-8") as f:
    for riga in f:
        record = json.loads(riga)
        tipo_count[record.get("type")] += 1
        n_tot += 1

print(f"Totale record OpenAlex Bergamo: {n_tot}")
print()
for tipo, c in tipo_count.most_common(15):
    print(f"{str(tipo):25s} {c:6d}  ({c/n_tot*100:.1f}%)")




import csv
 
n_tot = 0
n_con_doi = 0
 
with open("staging_openalex.csv", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        if row["ateneo"] == "Bergamo" and row["tipo"] == "article":
            n_tot += 1
            if row["doi"]:
                n_con_doi += 1
 
print(f"Articoli Bergamo su OpenAlex: {n_tot}")
print(f"Di cui con DOI popolato in OpenAlex: {n_con_doi} ({n_con_doi/n_tot*100:.1f}%)")
 