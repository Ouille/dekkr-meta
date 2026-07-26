# dekkr-meta

Service local d'enrichissement de métadonnées musicales pour [DekkR](https://github.com/Ouille/DekkR).

Il fait correspondre les fichiers audio d'une collection locale avec la base
Discogs et retourne **genre, style, année, label, pays** ainsi que l'URL de la
pochette.

Le matching se fait **hors ligne**, contre une copie locale du dump mensuel
Discogs. Seule la récupération des pochettes nécessite un accès réseau.

---

## Pourquoi un service séparé

DekkR est destiné à être commercialisable. Les données Discogs et les briques
open-source de ce domaine (OneTagger est en GPL v3) imposent des contraintes
qui contamineraient le produit principal. `dekkr-meta` est donc un **add-on
gratuit et indépendant** : DekkR l'appelle en HTTP local, sans jamais embarquer
son code.

| Source | Licence | Usage ici |
| :--- | :--- | :--- |
| Dump Discogs | CC0 — aucun droit réservé | copie locale, usage libre |
| API Discogs (pochettes) | CGU Discogs | URLs relayées, **jamais stockées** |
| dekkr-meta | MIT | add-on autonome |

---

## Installation

### Application Windows (recommandé)

Récupérer `dekkr-meta.exe` depuis les *Releases*, puis le lancer. Une icône
apparaît dans la barre des tâches. Au premier lancement, la base est absente :
clic droit sur l'icône → **Importer la base Discogs**.

L'icône indique l'état d'un coup d'œil :

| Couleur | État |
| :--- | :--- |
| 🟠 orange | base absente — import à lancer |
| 🟡 jaune | import en cours |
| 🟢 vert | base prête, service opérationnel |
| 🔴 rouge | erreur |

Le menu donne accès à la fenêtre de statut, aux paramètres (emplacement de la
base, jeton Discogs, seuil, port) et au démarrage automatique avec Windows.

La configuration est enregistrée dans
`%APPDATA%\dekkr-meta\config.json`.

### Depuis les sources

```bash
git clone https://github.com/Ouille/dekkr-meta
cd dekkr-meta
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py
```

Pour reconstruire l'exécutable :

```bash
venv\Scripts\pyinstaller build.spec --noconfirm --clean
```

---

## Import de la base

Depuis l'icône de la barre des tâches, ou en ligne de commande :

```bash
venv\Scripts\python import_cli.py
```

Télécharge le dump le plus récent et le charge en SQLite.

Mesuré sur le dump `20260701` :

| | |
| :--- | :--- |
| Téléchargement | 10,4 Go compressés |
| Durée | 47 min (40 min de lecture + 7 min d'index) |
| Base produite | **16,9 Go** |
| Contenu | 19,3 M sorties, 187 M couples artiste/titre |
| Complétude | label 100 %, genre 100 %, style 97,7 %, année 97,7 % |

Prévoir ~20 Go d'espace libre.

Pour un essai rapide sans tout télécharger :

```bash
venv\Scripts\python import_cli.py --slice-mb 120
```

---

## Lancement du service

L'exécutable démarre le service automatiquement. Il écoute sur
`http://127.0.0.1:7433` ; la documentation interactive est sur `/docs`.

Pour lancer l'API seule, sans icône ni fenêtres :

```bash
venv\Scripts\python server.py
```

---

## API

### `GET /status`

État du service et de la base.

```json
{
  "db_ready": true,
  "releases_count": 19267094,
  "entries_count": 187070107,
  "dump_date": "20260701",
  "discogs_token": true,
  "import": { "running": false, "step": "Terminé" }
}
```

### `POST /match`

```json
// requête
{ "artist": "The Persuader", "title": "Östermalm" }

// réponse
{
  "matched": true,
  "score": 100.0,
  "release_id": 1,
  "matched_artist": "The Persuader",
  "matched_title": "Östermalm",
  "genre": ["Electronic"],
  "style": ["Deep House"],
  "year": 1999,
  "label": "Svek",
  "country": "Sweden",
  "url_cover": "https://i.discogs.com/..."
}
```

Sans correspondance au-dessus du seuil : `{ "matched": false, "score": 0 }`.

### `POST /match/batch?covers=true`

Même chose pour une liste. Chaque élément porte un `id` restitué tel quel.
Les appels pochettes sont cadencés à 1/s ; les morceaux non trouvés n'en
consomment aucun. Passer `covers=false` pour ne faire aucun appel réseau.

### `POST /db/update?force=false`

Relance l'import en tâche de fond. Refuse un dump de moins de 31 jours sauf
`force=true`. Suivre l'avancement via `/status`.

---

## Fonctionnement du matching

Un DJ possède des **morceaux** ; Discogs indexe des **sorties**. Un fichier
« The Persuader — Östermalm » n'apparaît nulle part dans le titre de la sortie,
qui est « Stockholm ». La table `entries` contient donc, pour chaque sortie, le
titre de la sortie **et** chaque titre de sa tracklist — soit 9,7 lignes par
sortie en moyenne.

1. **Normalisation** — retrait des numéros de piste en préfixe, des mentions
   `(Original Mix)`, `[Remix]`, `feat. X`, de la ponctuation et de la casse.
2. **Présélection** — recherche plein texte FTS5 (`unicode61
   remove_diacritics`), en tentant `artiste + titre`, puis `titre` seul, puis
   `artiste` seul.
3. **Notation** — `rapidfuzz.token_sort_ratio` sur l'artiste et sur le titre.
   Score combiné : `artiste × 0,4 + titre × 0,6`.
4. **Seuil** — en dessous de `MATCH_THRESHOLD` (85 par défaut), aucun résultat
   n'est retourné : mieux vaut pas de métadonnée qu'une métadonnée fausse.

---

## Configuration

Réglable depuis **Paramètres** (menu de l'icône), ou directement dans
`%APPDATA%\dekkr-meta\config.json` :

| Clé | Défaut | Rôle |
| :--- | :--- | :--- |
| `port` | `7433` | port d'écoute (redémarrage requis) |
| `match_threshold` | `85` | score minimum retenu |
| `discogs_token` | — | jeton personnel, requis pour les pochettes |
| `db_path` | voir ci-dessous | emplacement de la base |
| `index_tracks` | `true` | indexer les tracklists (⚠️ à `false`, seuls les titres de sortie sont cherchables) |
| `autostart` | `false` | démarrage avec Windows |

Au tout premier lancement, une base `discogs.db` déjà présente à côté de
l'exécutable, dans son dossier parent ou dans le dossier courant est adoptée
plutôt que réclamée — un import coûte une heure. À défaut, la base est créée
dans `%APPDATA%\dekkr-meta\`. Le chemin retenu est ensuite figé dans
`config.json` ; **Paramètres** permet d'en désigner un autre, y compris sur un
autre disque.

Les variables d'environnement `PORT`, `MATCH_THRESHOLD`, `DISCOGS_TOKEN` et
`DB_PATH` restent prioritaires, pour le développement.

---

## Limites connues

- Les URL de pochettes Discogs **expirent** : elles ne doivent pas être
  conservées durablement côté client, mais redemandées.
- Sans `DISCOGS_TOKEN`, tout fonctionne sauf les pochettes (`url_cover: null`).
- Les fichiers dépourvus de tags ID3 exploitables ne peuvent pas être matchés :
  le service ne fait pas d'empreinte audio.

---

## Licence

MIT.

Les données Discogs sont distribuées sous CC0. Ce projet n'est pas affilié à
Discogs.
