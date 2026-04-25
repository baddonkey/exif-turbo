"""Populate PO files with translations for all supported languages."""

from __future__ import annotations

from pathlib import Path

import babel.messages.pofile as pofile  # type: ignore[import-untyped]

LOCALES_DIR = Path(__file__).parent.parent / "src" / "exif_turbo" / "i18n" / "locales"

# fmt: off
TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        # ── Tabs ────────────────────────────────────────────────────────────
        "Search": "Suchen",
        "Browse": "Durchsuchen",
        "Indexed Folders": "Indizierte Ordner",
        "Settings": "Einstellungen",
        # ── Menu ────────────────────────────────────────────────────────────
        "About exif-turbo": "Über exif-turbo",
        "&File": "&Datei",
        "E&xit": "&Beenden",
        "&Help": "&Hilfe",
        "&About": "Ü&ber",
        # ── Lock screen ─────────────────────────────────────────────────────
        "Enter the database password": "Datenbankpasswort eingeben",
        "Password": "Passwort",
        "New passphrase": "Neues Passwort",
        "Confirm passphrase": "Passwort best\u00e4tigen",
        "Create Database": "Datenbank erstellen",
        "Unlock": "Entsperren",
        "Create a passphrase for your new database": "Passwort f\u00fcr neue Datenbank festlegen",
        "This passphrase encrypts your entire image index. Use at least 12 characters and a mix of letters, numbers, and symbols. There is no way to recover a lost passphrase.":
            "Dieses Passwort verschl\u00fcsselt den gesamten Bildindex. Verwenden Sie mindestens 12 Zeichen und eine Kombination aus Buchstaben, Ziffern und Sonderzeichen. Ein verlorenes Passwort kann nicht wiederhergestellt werden.",
        "Passphrases do not match": "Passw\u00f6rter stimmen nicht \u00fcberein",
        "Enter the database password to continue": "Datenbankpasswort eingeben, um fortzufahren",
        # ── Progress panel ──────────────────────────────────────────────────
        "Indexing folder %1 of %2": "Ordner %1 von %2 indizieren",
        "Indexing": "Indizierung",
        "Building Thumbnails": "Vorschaubilder werden erstellt",
        "files": "Dateien",
        "images": "Bilder",
        "Scanning for images\u2026": "Bilder werden gesucht\u2026",
        "Preparing\u2026": "Vorbereitung\u2026",
        "Canceling\u2026": "Abbrechen\u2026",
        "Cancel Indexing": "Indizierung abbrechen",
        "Cancel Thumbnails": "Vorschaubilder abbrechen",
        # ── Search tab ──────────────────────────────────────────────────────
        "Search EXIF metadata\u2026": "EXIF-Metadaten durchsuchen\u2026",
        "RESULTS": "ERGEBNISSE",
        "Sort": "Sortieren",
        "Name A\u2192Z": "Name A\u2192Z",
        "Name Z\u2192A": "Name Z\u2192A",
        "Path A\u2192Z": "Pfad A\u2192Z",
        "Path Z\u2192A": "Pfad Z\u2192A",
        "Newest first": "Neueste zuerst",
        "Oldest first": "\u00c4lteste zuerst",
        "Largest": "Gr\u00f6sste",
        "All": "Alle",
        "Camera": "Kamera",
        "Date": "Datum",
        "Dimensions": "Abmessungen",
        "Exposure": "Belichtung",
        "File size": "Dateigr\u00f6sse",
        "PREVIEW": "VORSCHAU",
        "METADATA": "METADATEN",
        "Find": "Suchen",
        "Find in metadata (Ctrl+F)": "In Metadaten suchen (Ctrl+F)",
        "Find in metadata\u2026": "In Metadaten suchen\u2026",
        "Previous match": "Vorherige \u00dcbereinstimmung",
        "Next match": "N\u00e4chste \u00dcbereinstimmung",
        "Select an image to see metadata": "Bild ausw\u00e4hlen, um Metadaten anzuzeigen",
        "EXIF TAGS": "EXIF-TAGS",
        "Tag": "Tag",
        "Value": "Wert",
        # ── Browse tab ──────────────────────────────────────────────────────
        "FOLDERS": "ORDNER",
        "No folders indexed yet": "Noch keine Ordner indiziert",
        "IMAGES": "BILDER",
        " images": " Bilder",
        "Select a folder": "Ordner ausw\u00e4hlen",
        "\u2190 Select a folder to browse images": "\u2190 Ordner ausw\u00e4hlen, um Bilder zu durchsuchen",
        # ── Settings tab ────────────────────────────────────────────────────
        "SETTINGS": "EINSTELLUNGEN",
        "Worker Threads": "Worker-Threads",
        "Number of parallel threads used for indexing and thumbnail generation. Higher values speed up processing but use more CPU and memory.":
            "Anzahl paralleler Threads f\u00fcr Indizierung und Vorschaubilderstellung. H\u00f6here Werte beschleunigen die Verarbeitung, ben\u00f6tigen jedoch mehr CPU und Speicher.",
        "thread": "Thread",
        "threads": "Threads",
        "Default: %1 (half of %2 detected CPU threads)": "Standard: %1 (H\u00e4lfte von %2 erkannten CPU-Threads)",
        "Indexing Blacklist": "Indizierungs-Blacklist",
        "File and folder name patterns to skip during indexing. Supports wildcards (e.g. *, ?).\nChanges take effect on the next rescan.":
            "Datei- und Ordnernamenmuster, die bei der Indizierung \u00fcbersprungen werden. Unterst\u00fctzt Platzhalter (z.B. *, ?).\n\u00c4nderungen werden beim n\u00e4chsten Neuindizieren wirksam.",
        "Remove": "Entfernen",
        "New pattern, e.g.  @eaDir  or  *.tmp": "Neues Muster, z.B.  @eaDir  oder  *.tmp",
        "Add": "Hinzuf\u00fcgen",
        "Patterns are matched against individual file or folder names (not full paths). Wildcards: * matches any characters, ? matches one character.":
            "Muster werden gegen einzelne Datei- oder Ordnernamen (keine vollst\u00e4ndigen Pfade) verglichen. Platzhalter: * entspricht beliebigen Zeichen, ? entspricht einem Zeichen.",
        "Language": "Sprache",
        "Theme": "Design",
        "Restart the application for language changes to take full effect.":
            "Starten Sie die Anwendung neu, damit die Sprach\u00e4nderung vollst\u00e4ndig wirksam wird.",
        # ── Status bar ──────────────────────────────────────────────────────
        "Indexing\u2026": "Indizierung\u2026",
        # ── Folders panel ───────────────────────────────────────────────────
        "Select Folder to Manage": "Ordner zur Verwaltung ausw\u00e4hlen",
        "Managed Folders": "Verwaltete Ordner",
        "Add Folder": "Ordner hinzuf\u00fcgen",
        "Rescan All": "Alle erneut indizieren",
        "Incrementally re-index all enabled folders": "Alle aktivierten Ordner inkrementell neu indizieren",
        "Full Rescan All": "Alle vollst\u00e4ndig neu indizieren",
        "Force re-extract EXIF for every file in all enabled folders":
            "EXIF f\u00fcr alle Dateien in allen aktivierten Ordnern neu extrahieren",
        "No folders managed yet.\nClick \"Add Folder\" to start tracking a folder.":
            "Noch keine Ordner verwaltet.\nKlicken Sie auf \u201eOrdner hinzuf\u00fcgen\u201c, um einen Ordner zu verfolgen.",
        "Folder is included in search results": "Ordner ist in den Suchergebnissen enthalten",
        "Folder is excluded from search results": "Ordner ist aus den Suchergebnissen ausgeschlossen",
        "Rescan": "Neu indizieren",
        "Re-index this folder (incremental)": "Diesen Ordner inkrementell neu indizieren",
        "Full Rescan": "Vollst\u00e4ndig neu indizieren",
        "Force re-extract EXIF for every file in this folder":
            "EXIF f\u00fcr alle Dateien in diesem Ordner neu extrahieren",
        "Remove this folder and delete its indexed images":
            "Diesen Ordner entfernen und seine indizierten Bilder l\u00f6schen",
        "Remove Folder": "Ordner entfernen",
        "Remove \"%1\" and delete all its indexed images from the database?":
            "\u201e%1\u201c entfernen und alle indizierten Bilder aus der Datenbank l\u00f6schen?",
        # ── Python status strings ────────────────────────────────────────────
        "Folder already tracked: {}": "Ordner bereits verfolgt: {}",
        "Indexing {}\u2026": "Indizierung von {}\u2026",
        "Indexed {} images": "{} Bilder indiziert",
        "Index failed: {}": "Indizierung fehlgeschlagen: {}",
        "Index canceled": "Indizierung abgebrochen",
        "Indexing\u2026 {} / {}": "Indizierung\u2026 {} / {}",
    },
    "fr": {
        # ── Tabs ────────────────────────────────────────────────────────────
        "Search": "Rechercher",
        "Browse": "Parcourir",
        "Indexed Folders": "Dossiers index\u00e9s",
        "Settings": "Param\u00e8tres",
        # ── Menu ────────────────────────────────────────────────────────────
        "About exif-turbo": "\u00c0 propos d\u2019exif-turbo",
        "&File": "&Fichier",
        "E&xit": "&Quitter",
        "&Help": "&Aide",
        "&About": "\u00c0 &propos",
        # ── Lock screen ─────────────────────────────────────────────────────
        "Enter the database password": "Saisir le mot de passe de la base de donn\u00e9es",
        "Password": "Mot de passe",
        "New passphrase": "Nouveau mot de passe",
        "Confirm passphrase": "Confirmer le mot de passe",
        "Create Database": "Cr\u00e9er la base de donn\u00e9es",
        "Unlock": "D\u00e9verrouiller",
        "Create a passphrase for your new database": "Cr\u00e9er un mot de passe pour votre nouvelle base de donn\u00e9es",
        "This passphrase encrypts your entire image index. Use at least 12 characters and a mix of letters, numbers, and symbols. There is no way to recover a lost passphrase.":
            "Ce mot de passe chiffre l\u2019int\u00e9gralit\u00e9 de votre index d\u2019images. Utilisez au moins 12 caract\u00e8res et un m\u00e9lange de lettres, chiffres et symboles. Il est impossible de r\u00e9cup\u00e9rer un mot de passe perdu.",
        "Passphrases do not match": "Les mots de passe ne correspondent pas",
        "Enter the database password to continue":
            "Saisir le mot de passe de la base de donn\u00e9es pour continuer",
        # ── Progress panel ──────────────────────────────────────────────────
        "Indexing folder %1 of %2": "Indexation du dossier %1 sur %2",
        "Indexing": "Indexation",
        "Building Thumbnails": "Cr\u00e9ation des miniatures",
        "files": "fichiers",
        "images": "images",
        "Scanning for images\u2026": "Recherche d\u2019images\u2026",
        "Preparing\u2026": "Pr\u00e9paration\u2026",
        "Canceling\u2026": "Annulation\u2026",
        "Cancel Indexing": "Annuler l\u2019indexation",
        "Cancel Thumbnails": "Annuler les miniatures",
        # ── Search tab ──────────────────────────────────────────────────────
        "Search EXIF metadata\u2026": "Rechercher dans les m\u00e9tadonn\u00e9es EXIF\u2026",
        "RESULTS": "R\u00c9SULTATS",
        "Sort": "Trier",
        "Name A\u2192Z": "Nom A\u2192Z",
        "Name Z\u2192A": "Nom Z\u2192A",
        "Path A\u2192Z": "Chemin A\u2192Z",
        "Path Z\u2192A": "Chemin Z\u2192A",
        "Newest first": "Plus r\u00e9cent d\u2019abord",
        "Oldest first": "Plus ancien d\u2019abord",
        "Largest": "Plus grand",
        "All": "Tout",
        "Camera": "Appareil",
        "Date": "Date",
        "Dimensions": "Dimensions",
        "Exposure": "Exposition",
        "File size": "Taille du fichier",
        "PREVIEW": "APC\u00c7U",
        "METADATA": "M\u00c9TADONN\u00c9ES",
        "Find": "Rechercher",
        "Find in metadata (Ctrl+F)": "Rechercher dans les m\u00e9tadonn\u00e9es (Ctrl+F)",
        "Find in metadata\u2026": "Rechercher dans les m\u00e9tadonn\u00e9es\u2026",
        "Previous match": "Correspondance pr\u00e9c\u00e9dente",
        "Next match": "Correspondance suivante",
        "Select an image to see metadata": "S\u00e9lectionner une image pour voir les m\u00e9tadonn\u00e9es",
        "EXIF TAGS": "TAGS EXIF",
        "Tag": "Tag",
        "Value": "Valeur",
        # ── Browse tab ──────────────────────────────────────────────────────
        "FOLDERS": "DOSSIERS",
        "No folders indexed yet": "Aucun dossier index\u00e9",
        "IMAGES": "IMAGES",
        " images": " images",
        "Select a folder": "S\u00e9lectionner un dossier",
        "\u2190 Select a folder to browse images": "\u2190 S\u00e9lectionner un dossier pour parcourir les images",
        # ── Settings tab ────────────────────────────────────────────────────
        "SETTINGS": "PARAM\u00c8TRES",
        "Worker Threads": "Threads de travail",
        "Number of parallel threads used for indexing and thumbnail generation. Higher values speed up processing but use more CPU and memory.":
            "Nombre de threads parall\u00e8les pour l\u2019indexation et la cr\u00e9ation de miniatures. Des valeurs plus \u00e9lev\u00e9es acc\u00e9l\u00e8rent le traitement mais utilisent plus de CPU et de m\u00e9moire.",
        "thread": "thread",
        "threads": "threads",
        "Default: %1 (half of %2 detected CPU threads)": "Par d\u00e9faut\u00a0: %1 (moiti\u00e9 de %2 threads CPU d\u00e9tect\u00e9s)",
        "Indexing Blacklist": "Liste noire d\u2019indexation",
        "File and folder name patterns to skip during indexing. Supports wildcards (e.g. *, ?).\nChanges take effect on the next rescan.":
            "Mod\u00e8les de noms de fichiers et dossiers \u00e0 ignorer lors de l\u2019indexation. Supporte les caract\u00e8res g\u00e9n\u00e9riques (ex. *, ?).\nLes modifications prennent effet lors de la prochaine r\u00e9indexation.",
        "Remove": "Supprimer",
        "New pattern, e.g.  @eaDir  or  *.tmp": "Nouveau mod\u00e8le, ex.\u00a0 @eaDir  ou  *.tmp",
        "Add": "Ajouter",
        "Patterns are matched against individual file or folder names (not full paths). Wildcards: * matches any characters, ? matches one character.":
            "Les mod\u00e8les sont compar\u00e9s aux noms de fichiers ou dossiers individuels (pas les chemins complets). Caract\u00e8res g\u00e9n\u00e9riques\u00a0: * correspond \u00e0 n\u2019importe quels caract\u00e8res, ? correspond \u00e0 un caract\u00e8re.",
        "Language": "Langue",
        "Theme": "Th\u00e8me",
        "Restart the application for language changes to take full effect.":
            "Red\u00e9marrez l\u2019application pour que le changement de langue prenne pleinement effet.",
        # ── Status bar ──────────────────────────────────────────────────────
        "Indexing\u2026": "Indexation\u2026",
        # ── Folders panel ───────────────────────────────────────────────────
        "Select Folder to Manage": "S\u00e9lectionner un dossier \u00e0 g\u00e9rer",
        "Managed Folders": "Dossiers g\u00e9r\u00e9s",
        "Add Folder": "Ajouter un dossier",
        "Rescan All": "R\u00e9indexer tout",
        "Incrementally re-index all enabled folders":
            "R\u00e9indexer de mani\u00e8re incr\u00e9mentielle tous les dossiers activ\u00e9s",
        "Full Rescan All": "R\u00e9indexation compl\u00e8te de tout",
        "Force re-extract EXIF for every file in all enabled folders":
            "Forcer la r\u00e9extraction EXIF pour chaque fichier de tous les dossiers activ\u00e9s",
        "No folders managed yet.\nClick \"Add Folder\" to start tracking a folder.":
            "Aucun dossier g\u00e9r\u00e9.\nCliquez sur \u00ab\u00a0Ajouter un dossier\u00a0\u00bb pour commencer \u00e0 suivre un dossier.",
        "Folder is included in search results": "Le dossier est inclus dans les r\u00e9sultats de recherche",
        "Folder is excluded from search results": "Le dossier est exclu des r\u00e9sultats de recherche",
        "Rescan": "R\u00e9indexer",
        "Re-index this folder (incremental)": "R\u00e9indexer ce dossier (incr\u00e9mentiel)",
        "Full Rescan": "R\u00e9indexation compl\u00e8te",
        "Force re-extract EXIF for every file in this folder":
            "Forcer la r\u00e9extraction EXIF pour chaque fichier de ce dossier",
        "Remove this folder and delete its indexed images":
            "Supprimer ce dossier et ses images index\u00e9es",
        "Remove Folder": "Supprimer le dossier",
        "Remove \"%1\" and delete all its indexed images from the database?":
            "Supprimer \u00ab\u00a0%1\u00a0\u00bb et toutes ses images index\u00e9es de la base de donn\u00e9es\u00a0?",
        # ── Python status strings ────────────────────────────────────────────
        "Folder already tracked: {}": "Dossier d\u00e9j\u00e0 suivi\u00a0: {}",
        "Indexing {}\u2026": "Indexation de {}\u2026",
        "Indexed {} images": "{} images index\u00e9es",
        "Index failed: {}": "Indexation \u00e9chou\u00e9e\u00a0: {}",
        "Index canceled": "Indexation annul\u00e9e",
        "Indexing\u2026 {} / {}": "Indexation\u2026 {} / {}",
    },
    "it": {
        # ── Tabs ────────────────────────────────────────────────────────────
        "Search": "Cerca",
        "Browse": "Sfoglia",
        "Indexed Folders": "Cartelle indicizzate",
        "Settings": "Impostazioni",
        # ── Menu ────────────────────────────────────────────────────────────
        "About exif-turbo": "Informazioni su exif-turbo",
        "&File": "&File",
        "E&xit": "&Esci",
        "&Help": "A&iuto",
        "&About": "&Informazioni",
        # ── Lock screen ─────────────────────────────────────────────────────
        "Enter the database password": "Inserisci la password del database",
        "Password": "Password",
        "New passphrase": "Nuova passphrase",
        "Confirm passphrase": "Conferma passphrase",
        "Create Database": "Crea database",
        "Unlock": "Sblocca",
        "Create a passphrase for your new database": "Crea una passphrase per il tuo nuovo database",
        "This passphrase encrypts your entire image index. Use at least 12 characters and a mix of letters, numbers, and symbols. There is no way to recover a lost passphrase.":
            "Questa passphrase cifra l\u2019intero indice delle immagini. Utilizza almeno 12 caratteri e una combinazione di lettere, numeri e simboli. Una passphrase persa non pu\u00f2 essere recuperata.",
        "Passphrases do not match": "Le passphrase non corrispondono",
        "Enter the database password to continue":
            "Inserisci la password del database per continuare",
        # ── Progress panel ──────────────────────────────────────────────────
        "Indexing folder %1 of %2": "Indicizzazione cartella %1 di %2",
        "Indexing": "Indicizzazione",
        "Building Thumbnails": "Creazione miniature",
        "files": "file",
        "images": "immagini",
        "Scanning for images\u2026": "Ricerca immagini\u2026",
        "Preparing\u2026": "Preparazione\u2026",
        "Canceling\u2026": "Annullamento\u2026",
        "Cancel Indexing": "Annulla indicizzazione",
        "Cancel Thumbnails": "Annulla miniature",
        # ── Search tab ──────────────────────────────────────────────────────
        "Search EXIF metadata\u2026": "Cerca nei metadati EXIF\u2026",
        "RESULTS": "RISULTATI",
        "Sort": "Ordina",
        "Name A\u2192Z": "Nome A\u2192Z",
        "Name Z\u2192A": "Nome Z\u2192A",
        "Path A\u2192Z": "Percorso A\u2192Z",
        "Path Z\u2192A": "Percorso Z\u2192A",
        "Newest first": "Pi\u00f9 recente prima",
        "Oldest first": "Pi\u00f9 vecchio prima",
        "Largest": "Pi\u00f9 grande",
        "All": "Tutti",
        "Camera": "Fotocamera",
        "Date": "Data",
        "Dimensions": "Dimensioni",
        "Exposure": "Esposizione",
        "File size": "Dimensione file",
        "PREVIEW": "ANTEPRIMA",
        "METADATA": "METADATI",
        "Find": "Trova",
        "Find in metadata (Ctrl+F)": "Trova nei metadati (Ctrl+F)",
        "Find in metadata\u2026": "Trova nei metadati\u2026",
        "Previous match": "Corrispondenza precedente",
        "Next match": "Corrispondenza successiva",
        "Select an image to see metadata":
            "Seleziona un\u2019immagine per vedere i metadati",
        "EXIF TAGS": "TAG EXIF",
        "Tag": "Tag",
        "Value": "Valore",
        # ── Browse tab ──────────────────────────────────────────────────────
        "FOLDERS": "CARTELLE",
        "No folders indexed yet": "Nessuna cartella indicizzata",
        "IMAGES": "IMMAGINI",
        " images": " immagini",
        "Select a folder": "Seleziona una cartella",
        "\u2190 Select a folder to browse images":
            "\u2190 Seleziona una cartella per sfogliare le immagini",
        # ── Settings tab ────────────────────────────────────────────────────
        "SETTINGS": "IMPOSTAZIONI",
        "Worker Threads": "Thread di lavoro",
        "Number of parallel threads used for indexing and thumbnail generation. Higher values speed up processing but use more CPU and memory.":
            "Numero di thread paralleli per l\u2019indicizzazione e la generazione di miniature. Valori pi\u00f9 alti accelerano l\u2019elaborazione ma utilizzano pi\u00f9 CPU e memoria.",
        "thread": "thread",
        "threads": "thread",
        "Default: %1 (half of %2 detected CPU threads)":
            "Predefinito: %1 (met\u00e0 di %2 thread CPU rilevati)",
        "Indexing Blacklist": "Lista nera indicizzazione",
        "File and folder name patterns to skip during indexing. Supports wildcards (e.g. *, ?).\nChanges take effect on the next rescan.":
            "Modelli di nomi di file e cartelle da ignorare durante l\u2019indicizzazione. Supporta caratteri jolly (es. *, ?).\nLe modifiche hanno effetto alla prossima reindicizzazione.",
        "Remove": "Rimuovi",
        "New pattern, e.g.  @eaDir  or  *.tmp": "Nuovo modello, es.  @eaDir  o  *.tmp",
        "Add": "Aggiungi",
        "Patterns are matched against individual file or folder names (not full paths). Wildcards: * matches any characters, ? matches one character.":
            "I modelli vengono confrontati con nomi di file o cartelle singoli (non percorsi completi). Caratteri jolly: * corrisponde a qualsiasi carattere, ? corrisponde a un carattere.",
        "Language": "Lingua",
        "Theme": "Tema",
        "Restart the application for language changes to take full effect.":
            "Riavvia l\u2019applicazione affinch\u00e9 le modifiche alla lingua abbiano pieno effetto.",
        # ── Status bar ──────────────────────────────────────────────────────
        "Indexing\u2026": "Indicizzazione\u2026",
        # ── Folders panel ───────────────────────────────────────────────────
        "Select Folder to Manage": "Seleziona cartella da gestire",
        "Managed Folders": "Cartelle gestite",
        "Add Folder": "Aggiungi cartella",
        "Rescan All": "Reindicizza tutto",
        "Incrementally re-index all enabled folders":
            "Reindicizza in modo incrementale tutte le cartelle abilitate",
        "Full Rescan All": "Reindicizzazione completa di tutto",
        "Force re-extract EXIF for every file in all enabled folders":
            "Forza la rieestrazione EXIF per ogni file in tutte le cartelle abilitate",
        "No folders managed yet.\nClick \"Add Folder\" to start tracking a folder.":
            "Nessuna cartella gestita.\nClicca su \u00abAggiungi cartella\u00bb per iniziare a monitorare una cartella.",
        "Folder is included in search results":
            "La cartella \u00e8 inclusa nei risultati di ricerca",
        "Folder is excluded from search results":
            "La cartella \u00e8 esclusa dai risultati di ricerca",
        "Rescan": "Reindicizza",
        "Re-index this folder (incremental)": "Reindicizza questa cartella (incrementale)",
        "Full Rescan": "Reindicizzazione completa",
        "Force re-extract EXIF for every file in this folder":
            "Forza la rieestrazione EXIF per ogni file in questa cartella",
        "Remove this folder and delete its indexed images":
            "Rimuovi questa cartella ed elimina le sue immagini indicizzate",
        "Remove Folder": "Rimuovi cartella",
        "Remove \"%1\" and delete all its indexed images from the database?":
            "Rimuovere \u00ab%1\u00bb ed eliminare tutte le sue immagini indicizzate dal database?",
        # ── Python status strings ────────────────────────────────────────────
        "Folder already tracked: {}": "Cartella gi\u00e0 monitorata: {}",
        "Indexing {}\u2026": "Indicizzazione {}\u2026",
        "Indexed {} images": "{} immagini indicizzate",
        "Index failed: {}": "Indicizzazione fallita: {}",
        "Index canceled": "Indicizzazione annullata",
        "Indexing\u2026 {} / {}": "Indicizzazione\u2026 {} / {}",
    },
    "rm": {
        # ── Tabs ────────────────────────────────────────────────────────────
        "Search": "Tschertgar",
        "Browse": "Navigar",
        "Indexed Folders": "Cartellas indexadas",
        "Settings": "Parameters",
        # ── Menu ────────────────────────────────────────────────────────────
        "About exif-turbo": "Davart exif-turbo",
        "&File": "&Datoteca",
        "E&xit": "&Serrar",
        "&Help": "&Agid",
        "&About": "&Davart",
        # ── Lock screen ─────────────────────────────────────────────────────
        "Enter the database password": "Endatar la pled-clav da la banca da datas",
        "Password": "Pled-clav",
        "New passphrase": "Nova pled-clav",
        "Confirm passphrase": "Confermar la pled-clav",
        "Create Database": "Crear banca da datas",
        "Unlock": "Avrir",
        "Create a passphrase for your new database": "Crear ina pled-clav per la nova banca da datas",
        "This passphrase encrypts your entire image index. Use at least 12 characters and a mix of letters, numbers, and symbols. There is no way to recover a lost passphrase.":
            "Questa pled-clav cifrescha l\u2019entir index da maletgs. Duvrai almain 12 caratters ed ina mesadad da lettras, cifras e simbols. Ina pled-clav persa na po betg vegnir recuperada.",
        "Passphrases do not match": "Las pled-clavs na correspundan betg",
        "Enter the database password to continue":
            "Endatar la pled-clav da la banca da datas per cuntinuar",
        # ── Progress panel ──────────────────────────────────────────────────
        "Indexing folder %1 of %2": "Indexaziun da la cartella %1 da %2",
        "Indexing": "Indexaziun",
        "Building Thumbnails": "Creaziun da miniatures",
        "files": "datotecas",
        "images": "maletgs",
        "Scanning for images\u2026": "Tscherca da maletgs\u2026",
        "Preparing\u2026": "Preparaziun\u2026",
        "Canceling\u2026": "Interruziun\u2026",
        "Cancel Indexing": "Interrumper indexaziun",
        "Cancel Thumbnails": "Interrumper miniatures",
        # ── Search tab ──────────────────────────────────────────────────────
        "Search EXIF metadata\u2026": "Tschertgar en metadata EXIF\u2026",
        "RESULTS": "RESULTATS",
        "Sort": "Sortir",
        "Name A\u2192Z": "Num A\u2192Z",
        "Name Z\u2192A": "Num Z\u2192A",
        "Path A\u2192Z": "Traject A\u2192Z",
        "Path Z\u2192A": "Traject Z\u2192A",
        "Newest first": "Pli novas emprim",
        "Oldest first": "Pli vegl emprim",
        "Largest": "Pli gronds",
        "All": "Tuts",
        "Camera": "Camera",
        "Date": "Data",
        "Dimensions": "Dimensiuns",
        "Exposure": "Exposiziun",
        "File size": "Grondezza da datoteca",
        "PREVIEW": "PREVISTA",
        "METADATA": "METADATA",
        "Find": "Tschertgar",
        "Find in metadata (Ctrl+F)": "Tschertgar en metadata (Ctrl+F)",
        "Find in metadata\u2026": "Tschertgar en metadata\u2026",
        "Previous match": "Resultaten precedent",
        "Next match": "Proxim resultaten",
        "Select an image to see metadata": "Tscherner in maletg per vesair metadata",
        "EXIF TAGS": "TAGS EXIF",
        "Tag": "Tag",
        "Value": "Valur",
        # ── Browse tab ──────────────────────────────────────────────────────
        "FOLDERS": "CARTELLAS",
        "No folders indexed yet": "Anc naginas cartellas indexadas",
        "IMAGES": "MALETGS",
        " images": " maletgs",
        "Select a folder": "Tscherner ina cartella",
        "\u2190 Select a folder to browse images":
            "\u2190 Tscherner ina cartella per navigar ils maletgs",
        # ── Settings tab ────────────────────────────────────────────────────
        "SETTINGS": "PARAMETERS",
        "Worker Threads": "Threads da lavur",
        "Number of parallel threads used for indexing and thumbnail generation. Higher values speed up processing but use more CPU and memory.":
            "Dumber da threads parallels per indexaziun e creaziun da miniatures. Valurs pli autas acceleran la tractaziun ma duvran dapli CPU e memoria.",
        "thread": "thread",
        "threads": "threads",
        "Default: %1 (half of %2 detected CPU threads)":
            "Standard: %1 (mesadad da %2 threads CPU detektads)",
        "Indexing Blacklist": "Glista naira d\u2019indexaziun",
        "File and folder name patterns to skip during indexing. Supports wildcards (e.g. *, ?).\nChanges take effect on the next rescan.":
            "Schemes da nums da datotecas e cartellas da sursiglir durant l\u2019indexaziun. Supporta caratters jolly (p.ex. *, ?).\nMutaziuns vegnan activas en la proxima re-indexaziun.",
        "Remove": "Stizzar",
        "New pattern, e.g.  @eaDir  or  *.tmp": "Nov schema, p.ex.  @eaDir  u  *.tmp",
        "Add": "Agiuntar",
        "Patterns are matched against individual file or folder names (not full paths). Wildcards: * matches any characters, ? matches one character.":
            "Ils schemes vegnan comparads cun nums singuls da datotecas u cartella (betg trajects cumplains). Caratters jolly: * correspunda a insaquants caratters, ? correspunda ad in caracter.",
        "Language": "Lingua",
        "Theme": "Tema",
        "Restart the application for language changes to take full effect.":
            "Restartad l\u2019applicaziun per che la midada da lingua saja daditg activa.",
        # ── Folders panel ───────────────────────────────────────────────────
        "Select Folder to Manage": "Tscherner cartella per manaschar",
        "Managed Folders": "Cartellas manasgiadas",
        "Add Folder": "Agiuntar cartella",
        "Rescan All": "Re-indexar tut",
        "Incrementally re-index all enabled folders":
            "Re-indexar incrementalmain tut las cartellas activadas",
        "Full Rescan All": "Re-indexaziun cumplaina da tut",
        "Force re-extract EXIF for every file in all enabled folders":
            "Forczar l\u2019extracziun EXIF per mintga datoteca en tut las cartellas activadas",
        "No folders managed yet.\nClick \"Add Folder\" to start tracking a folder.":
            "Anc naginas cartellas manasgiadas.\nClicchai sin \u201eAgiuntar cartella\u201c per cumenzar a trackar ina cartella.",
        "Folder is included in search results":
            "La cartella \u00e8 inclusa en ils resultats da tschertga",
        "Folder is excluded from search results":
            "La cartella \u00e8 exclusa dals resultats da tschertga",
        "Rescan": "Re-indexar",
        "Re-index this folder (incremental)": "Re-indexar questa cartella (incremental)",
        "Full Rescan": "Re-indexaziun cumplaina",
        "Force re-extract EXIF for every file in this folder":
            "Forczar l\u2019extracziun EXIF per mintga datoteca en questa cartella",
        "Remove this folder and delete its indexed images":
            "Stizzar questa cartella e ses maletgs indexads",
        "Remove Folder": "Stizzar cartella",
        "Remove \"%1\" and delete all its indexed images from the database?":
            "Stizzar \u201e%1\u201c e tuts ses maletgs indexads da la banca da datas?",
        # ── Python status strings ────────────────────────────────────────────
        "Folder already tracked: {}": "Cartella gia trackata: {}",
        "Indexing {}\u2026": "Indexaziun {}\u2026",
        "Indexed {} images": "{} maletgs indexads",
        "Index failed: {}": "Indexaziun buca reussida: {}",
        "Index canceled": "Indexaziun interrutta",
        "Indexing\u2026 {} / {}": "Indexaziun\u2026 {} / {}",
    },
}
# fmt: on


def populate(lang: str, translations: dict[str, str]) -> None:
    po_path = LOCALES_DIR / lang / "LC_MESSAGES" / "exif_turbo.po"
    if not po_path.exists():
        print(f"  WARNING: {po_path} not found — skipping")
        return
    with po_path.open("rb") as f:
        catalog = pofile.read_po(f)
    changed = 0
    for msgid, msgstr in translations.items():
        if msgid in catalog:
            msg = catalog[msgid]
            if not msg.string:
                msg.string = msgstr
                changed += 1
    with po_path.open("wb") as f:
        pofile.write_po(f, catalog, include_previous=False)
    print(f"  {lang}: filled {changed} translation(s)")


def main() -> None:
    for lang, translations in TRANSLATIONS.items():
        populate(lang, translations)


if __name__ == "__main__":
    main()
