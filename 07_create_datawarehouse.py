"""
DATA WAREHOUSE - creazione schema e caricamento

Con questo script creo le tabelle del Data Warehouse in SQLite - per questi volumi non mi serve
altro - e ci carico dentro i CSV di staging che ho già pronto.

è lo stesso contenuto che ho già in staging, 
solo organizzato in schema a stella invece che in CSV piatti.
Tengo separate le due gerarchie di tipologia (Aisberg vs OpenAlex) perché
sono due tassonomie diverse (65 tipologie CINECA contro 15 tipi OpenAlex)
provare a mappare una sull'altra introdurrebbe un problema di data quality invece di risolverlo.

Output: datawarehouse.db 
"""

import csv
import json
import sqlite3
from pathlib import Path
 
BASE_DIR = Path(__file__).parent
MASTER_PATH = BASE_DIR / "Serie storiche USTAT Mur" / "master_normalizzazione_7_atenei.json"
STAGING_PUB_PATH = BASE_DIR / "staging_pubblicazione.csv"
STAGING_AUT_PATH = BASE_DIR / "staging_autore_pubblicazione.csv"
STAGING_OA_PATH = BASE_DIR / "staging_openalex.csv"
DB_PATH = BASE_DIR / "datawarehouse.db"
 
ATENEI = ["Bergamo", "Brescia", "Pavia", "Ferrara", "Modena e Reggio Emilia",
          "Trieste", "Ca' Foscari Venezia"]
 
# Tipi OpenAlex per cui ho verificato una copertura affidabile (confronto
# fatto su Bergamo: 83,6% per gli articoli, 0,5% per gli atti di convegno).
# Lo tengo come flag sulla dimensione, non come filtro che scarta righe:
# la scelta di quali tipi usare nel confronto resta un passo di analisi,
# non di ETL.
TIPI_INDICIZZAZIONE_AFFIDABILE = {"article", "review"}
 
# Non è un dato che trovo in nessuna fonte: è una scelta editoriale che ho
# fatto guardando a mano l'offerta formativa di ciascun ateneo.
HA_AREA_MEDICA = {
    "Bergamo": 0, "Brescia": 1, "Pavia": 1, "Ferrara": 1,
    "Modena e Reggio Emilia": 1, "Trieste": 1, "Ca' Foscari Venezia": 0,
}
 
 
def crea_schema(conn):
    """Creo tutte le tabelle. Uso DROP TABLE IF EXISTS così posso
    rilanciare lo script quante volte voglio senza dover cancellare a
    mano il file .db ogni volta."""
    conn.executescript("""
        DROP TABLE IF EXISTS Bridge_Pubblicazione_Autore;
        DROP TABLE IF EXISTS Fact_Pubblicazione_Aisberg;
        DROP TABLE IF EXISTS Fact_Pubblicazione_OpenAlex;
        DROP TABLE IF EXISTS Fact_Personale_Ateneo;
        DROP TABLE IF EXISTS Dim_Dipartimento;
        DROP TABLE IF EXISTS Dim_Area_Disciplinare;
        DROP TABLE IF EXISTS Dim_Tipo_Pubblicazione;
        DROP TABLE IF EXISTS Dim_Anno;
        DROP TABLE IF EXISTS Dim_Ateneo;
 
        CREATE TABLE Dim_Ateneo (
            ateneo_id INTEGER PRIMARY KEY,
            nome_ateneo TEXT NOT NULL UNIQUE,
            anno_fondazione INTEGER,
            laureati_2025 INTEGER,
            laureati_primo_livello_2025 INTEGER,
            laureati_secondo_livello_2025 INTEGER,
            ha_area_medica INTEGER  -- 0/1, flag che mi serve per il confronto per area
        );
 
        CREATE TABLE Dim_Anno (
            anno INTEGER PRIMARY KEY
        );
 
        CREATE TABLE Dim_Tipo_Pubblicazione (
            tipo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_openalex TEXT NOT NULL UNIQUE,
            indicizzazione_affidabile INTEGER  -- 0/1, da confronto Aisberg/OpenAlex su Bergamo
        );
 
        CREATE TABLE Dim_Area_Disciplinare (
            area_id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT,
            field TEXT,
            subfield TEXT,
            UNIQUE(domain, field, subfield)
        );
 
        CREATE TABLE Dim_Dipartimento (
            dipartimento_id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_dipartimento TEXT NOT NULL,
            attivo_dal TEXT,
            attivo_al TEXT,
            UNIQUE(nome_dipartimento, attivo_dal, attivo_al)
        );
 
        CREATE TABLE Fact_Pubblicazione_OpenAlex (
            pubblicazione_id TEXT PRIMARY KEY,  -- openalex_id
            ateneo_id INTEGER REFERENCES Dim_Ateneo(ateneo_id),
            anno INTEGER REFERENCES Dim_Anno(anno),
            tipo_id INTEGER REFERENCES Dim_Tipo_Pubblicazione(tipo_id),
            area_id INTEGER REFERENCES Dim_Area_Disciplinare(area_id),
            doi TEXT,
            title TEXT,
            lingua TEXT,
            is_retracted INTEGER,
            is_oa INTEGER,
            oa_status TEXT,
            n_autori INTEGER,
            n_istituzioni_distinte INTEGER,
            n_paesi_distinti INTEGER
        );
 
        CREATE TABLE Fact_Personale_Ateneo (
            ateneo_id INTEGER REFERENCES Dim_Ateneo(ateneo_id),
            anno INTEGER REFERENCES Dim_Anno(anno),
            docenti_ricercatori_narrow INTEGER,
            docenti_ricercatori_broad INTEGER,
            pta INTEGER,
            cel INTEGER,
            iscritti INTEGER,
            PRIMARY KEY (ateneo_id, anno)
        );
 
        CREATE TABLE Fact_Pubblicazione_Aisberg (
            handle TEXT PRIMARY KEY,
            id_prodotto TEXT,
            titolo TEXT,
            anno INTEGER REFERENCES Dim_Anno(anno),
            tipologia TEXT,
            sottotipologia TEXT,
            nr_autori_dichiarato INTEGER,
            issn TEXT, isbn TEXT, e_isbn TEXT, ismn TEXT,
            wos_id TEXT, scopus_id TEXT, pubmed_id TEXT,
            doi TEXT, scopus_doi TEXT, wos_doi TEXT,
            oa_type TEXT
        );
 
        CREATE TABLE Bridge_Pubblicazione_Autore (
            handle TEXT REFERENCES Fact_Pubblicazione_Aisberg(handle),
            autore_nome TEXT,
            autore_cognome TEXT,
            id_persona_iris TEXT,
            dipartimento_id INTEGER REFERENCES Dim_Dipartimento(dipartimento_id),
            corresponding TEXT
        );
    """)
 
 
def carica_dim_ateneo(conn):
    """Popolo Dim_Ateneo dal file master unico, che ho già pronto con
    laureati, anno di fondazione e le serie storiche di tutto il resto.
    Il flag area medica non è in nessuna fonte: è una scelta editoriale
    che ho fatto io guardando l'offerta formativa di ciascun ateneo."""
    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
 
    for i, ateneo in enumerate(ATENEI, start=1):
        m = master.get(ateneo, {})
        conn.execute(
            "INSERT INTO Dim_Ateneo (ateneo_id, nome_ateneo, anno_fondazione, "
            "laureati_2025, laureati_primo_livello_2025, laureati_secondo_livello_2025, "
            "ha_area_medica) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i, ateneo, m.get("anno_fondazione"), m.get("laureati_almalaurea"),
             m.get("laureati_primo_livello"), m.get("laureati_secondo_livello"),
             HA_AREA_MEDICA[ateneo]),
        )
 
 
def carica_dim_anno(conn):
    for anno in range(2015, 2026):
        conn.execute("INSERT INTO Dim_Anno (anno) VALUES (?)", (anno,))
 
 
def get_or_create_tipo(conn, cache, tipo_openalex):
    if tipo_openalex not in cache:
        affidabile = 1 if tipo_openalex in TIPI_INDICIZZAZIONE_AFFIDABILE else 0
        cur = conn.execute(
            "INSERT INTO Dim_Tipo_Pubblicazione (tipo_openalex, indicizzazione_affidabile) "
            "VALUES (?, ?)", (tipo_openalex, affidabile),
        )
        cache[tipo_openalex] = cur.lastrowid
    return cache[tipo_openalex]
 
 
def get_or_create_area(conn, cache, domain, field, subfield):
    key = (domain, field, subfield)
    if key not in cache:
        cur = conn.execute(
            "INSERT INTO Dim_Area_Disciplinare (domain, field, subfield) VALUES (?, ?, ?)",
            key,
        )
        cache[key] = cur.lastrowid
    return cache[key]
 
 
def carica_fact_openalex(conn):
    """Leggo staging_openalex.csv riga per riga e popolo la fact table.
    Le dimensioni tipo/area le creo al volo (get_or_create) invece di
    fare un primo passaggio a parte per raccoglierle - con questi volumi
    non c'è differenza di prestazioni sensibile, e mi tiene il codice
    più semplice."""
    ateneo_id_map = {nome: i for i, nome in enumerate(ATENEI, start=1)}
    tipo_cache, area_cache = {}, {}
    path = STAGING_OA_PATH
    if not path.exists():
        print(f"ATTENZIONE: non trovo {path}, salto Fact_Pubblicazione_OpenAlex")
        return
 
    n = 0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ateneo_id = ateneo_id_map.get(row["ateneo"])
            anno = int(row["anno"]) if row["anno"] else None
            tipo_id = get_or_create_tipo(conn, tipo_cache, row["tipo"] or "unknown")
            area_id = get_or_create_area(
                conn, area_cache, row["domain"] or None, row["field"] or None, row["subfield"] or None
            )
            conn.execute(
                "INSERT OR IGNORE INTO Fact_Pubblicazione_OpenAlex "
                "(pubblicazione_id, ateneo_id, anno, tipo_id, area_id, doi, title, lingua, "
                "is_retracted, is_oa, oa_status, n_autori, n_istituzioni_distinte, n_paesi_distinti) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["openalex_id"], ateneo_id, anno, tipo_id, area_id, row["doi"], row["title"],
                 row["lingua"], row["is_retracted"], row["is_oa"], row["oa_status"],
                 row["n_autori"] or None, row["n_istituzioni_distinte"] or None,
                 row["n_paesi_distinti"] or None),
            )
            n += 1
    print(f"Fact_Pubblicazione_OpenAlex: {n} righe")
 
 
def carica_fact_personale(conn):
    """Leggo le serie storiche (docenti, iscritti, PTA) dal file master
    unico - le ho già incrociate una volta quando l'ho costruito, non ha
    senso tenerle sparse in più file."""
    ateneo_id_map = {nome: i for i, nome in enumerate(ATENEI, start=1)}
 
    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
 
    n = 0
    for ateneo in ATENEI:
        ateneo_id = ateneo_id_map[ateneo]
        m = master.get(ateneo, {})
        serie_docenti = m.get("serie_docenti_2015_2024", {})
        serie_iscritti = m.get("serie_iscritti_2015_2024", {})
        serie_pta = m.get("serie_pta_2015_2024", {})
 
        for anno in range(2015, 2025):  # queste serie arrivano solo al 2024
            anno_str = str(anno)
            anno_acc = f"{anno}/{anno+1}"
            d = serie_docenti.get(anno_str, {})
            p = serie_pta.get(anno_str, {})
            i_val = serie_iscritti.get(anno_acc)
            conn.execute(
                "INSERT OR REPLACE INTO Fact_Personale_Ateneo "
                "(ateneo_id, anno, docenti_ricercatori_narrow, docenti_ricercatori_broad, "
                "pta, cel, iscritti) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ateneo_id, anno, d.get("narrow"), d.get("broad"), p.get("PTA"), p.get("CEL"), i_val),
            )
            n += 1
    print(f"Fact_Personale_Ateneo: {n} righe")
 
 
def carica_aisberg(conn):
    """Carico le due tabelle Aisberg (solo Bergamo) che ho già in staging.
 
    Filtro al periodo 2015-2025: Dim_Anno contiene solo quegli anni (lo
    stesso range di OpenAlex e del personale), quindi caricare Aisberg
    senza filtro significava avere righe fact che puntano ad anni
    inesistenti nella dimensione - SQLite non lo segnala di default (le
    foreign key non sono verificate se non le attivo esplicitamente), ma
    è comunque un'incoerenza che non voglio nello schema. Tengo traccia
    degli handle che superano il filtro e li uso per filtrare a cascata
    anche il bridge autori, altrimenti mi ritroverei righe orfane lì.
 
    Dim_Dipartimento la costruisco al volo leggendo il bridge autori,
    perché è lì che vivono nome/date del dipartimento - non è un campo
    della pubblicazione, è un attributo dell'affiliazione dell'autore."""
    pub_path = STAGING_PUB_PATH
    aut_path = STAGING_AUT_PATH
    if not pub_path.exists() or not aut_path.exists():
        print("ATTENZIONE: non trovo gli staging Aisberg, salto quella parte")
        return
 
    ANNO_MIN, ANNO_MAX = 2015, 2025
    handle_validi = set()
    n_pub = 0
    n_esclusi = 0
    with open(pub_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            anno = int(float(row["anno"])) if row["anno"] else None
            if anno is None or not (ANNO_MIN <= anno <= ANNO_MAX):
                n_esclusi += 1
                continue
            handle_validi.add(row["handle"])
            conn.execute(
                "INSERT OR IGNORE INTO Fact_Pubblicazione_Aisberg "
                "(handle, id_prodotto, titolo, anno, tipologia, sottotipologia, "
                "nr_autori_dichiarato, issn, isbn, e_isbn, ismn, wos_id, scopus_id, "
                "pubmed_id, doi, scopus_doi, wos_doi, oa_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["handle"], row["id_prodotto"], row["titolo"], anno, row["tipologia"],
                 row["sottotipologia"], row["nr_autori_dichiarato"], row["issn"], row["isbn"],
                 row["e_isbn"], row["ismn"], row["wos_id"], row["scopus_id"], row["pubmed_id"],
                 row["doi"], row["scopus_doi"], row["wos_doi"], row["oa_type"]),
            )
            n_pub += 1
    print(f"Fact_Pubblicazione_Aisberg: {n_pub} righe caricate, {n_esclusi} escluse (anno fuori 2015-2025 o mancante)")
 
    dip_cache = {}
    n_bridge = 0
    n_bridge_esclusi = 0
    with open(aut_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["handle"] not in handle_validi:
                n_bridge_esclusi += 1
                continue
 
            dip_id = None
            if row["dipartimento_nome"]:
                key = (row["dipartimento_nome"], row["dipartimento_attivo_dal"] or "", row["dipartimento_attivo_al"] or "")
                if key not in dip_cache:
                    cur = conn.execute(
                        "INSERT INTO Dim_Dipartimento (nome_dipartimento, attivo_dal, attivo_al) "
                        "VALUES (?, ?, ?)",
                        (row["dipartimento_nome"], row["dipartimento_attivo_dal"] or None,
                         row["dipartimento_attivo_al"] or None),
                    )
                    dip_cache[key] = cur.lastrowid
                dip_id = dip_cache[key]
 
            conn.execute(
                "INSERT INTO Bridge_Pubblicazione_Autore "
                "(handle, autore_nome, autore_cognome, id_persona_iris, dipartimento_id, corresponding) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["handle"], row["autore_nome"], row["autore_cognome"], row["id_persona_iris"],
                 dip_id, row["corresponding"]),
            )
            n_bridge += 1
    print(f"Bridge_Pubblicazione_Autore: {n_bridge} righe caricate, {n_bridge_esclusi} escluse (fuori periodo), "
          f"{len(dip_cache)} dipartimenti distinti")
 
 
def main():
    if DB_PATH.exists():
        DB_PATH.unlink()  # riparto sempre da un file pulito, non appendo a un db vecchio
 
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite non lo fa di default:
    # lo attivo per essere avvisato se introduco incoerenze come quella
    # che ho appena corretto (fact che punta ad anni fuori da Dim_Anno)
    crea_schema(conn)
    carica_dim_ateneo(conn)
    carica_dim_anno(conn)
    carica_fact_openalex(conn)
    carica_fact_personale(conn)
    carica_aisberg(conn)
    conn.commit()
    conn.close()
 
    print(f"\nData Warehouse creato in {DB_PATH}")
 
 
if __name__ == "__main__":
    main()