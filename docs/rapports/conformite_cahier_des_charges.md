# Tujya : conformité au cahier des charges du module

Note de conformité au document `Guide_Projet_Deep_Learning_Avance_MLops.pdf` (Deep Learning
Avancé, Cycle Ingénieur IA & Data Science, 3ᵉ année, 2026‑2027, enseignant Haythem
Ghazouani). Rédigée le **2026‑11‑17**, à partir du dépôt lui‑même : chaque ligne renvoie au
fichier qui la justifie, et les mesures viennent soit des fichiers servis, soit d'un appel
réel aux points d'entrée, jamais d'une estimation.

> Tujya est un outil d'information : il ne remplace pas un pharmacien ou un médecin, ne
> donne jamais de dose et ne dit jamais qu'une association est « sûre ».

**Mise à jour du 2026‑11‑22.** Le dossier de travail est de nouveau rattaché au dépôt
GitHub `mohamedraedbouhali/Tujya-1` ; `.github/workflows/` et les autres fichiers perdus
lors de la copie ont été restaurés depuis ce dépôt (voir §7.1).

## 1. Axe thématique retenu

**Axe 3 — Détection d'objets & segmentation en temps réel (YOLO)** (§3 du guide).

Cas d'usage : une personne qui prend plusieurs médicaments photographie un ou plusieurs
comprimés ; l'application les **détecte**, les **identifie** parmi 150 produits, remonte
aux principes actifs et **vérifie les interactions**. Un seul axe majeur est traité, comme
le guide l'exige ; l'agent conversationnel du module 2 est un travail séparé.

| Attendu de l'axe 3 | Réalisation | Référence |
|---|---|---|
| Famille YOLO (v8/v10/v11) | YOLO11n (détection) + YOLO11s‑cls (identification) | `docs/VISION.md` |
| Métriques mAP@[.5:.95] | mAP50 **0,9695**, mAP50‑95 **0,8498** | `vision/runs/detect-20261101-194254/summary.json` |
| NMS optimisée | NMS gloutonne réimplémentée en numpy | `backend/app/scanner.py` |
| Boîtes et scores superposés | canvas React + `POST /api/predict/visualize` | §3, §2.4 |
| Flux vidéo / webcam | capture webcam, ~1 image/s | `frontend/src/pages/ScanPage.tsx` |

## 2. §5.1 — Backend FastAPI

| Exigence du guide | État | Où |
|---|---|---|
| Swagger/OpenAPI sur `/docs` | **Conforme** | `backend/app/main.py` (`docs_url="/docs"`) |
| Validation Pydantic stricte en entrée et en sortie | **Conforme** | `backend/app/schemas.py`, `response_model=` sur chaque route |
| `GET /health` : état, GPU, version du modèle | **Conforme** (complété le 2026‑11‑17) | §2.1 |
| `GET /model/metadata` | **Conforme** (ajouté le 2026‑11‑17) | §2.2 |
| `POST /predict` | **Conforme** (alias ajouté le 2026‑11‑17) | §2.3 |
| `POST /predict/visualize` | **Conforme** (ajouté le 2026‑11‑17) | §2.4 |
| Codes HTTP sémantiques (400 / 503) | **Conforme avec un écart assumé** | §2.5 |

Les quatre noms du guide existent sous le préfixe `/api` utilisé par le reste de
l'application : `POST /api/predict`, `POST /api/predict/visualize`,
`GET /api/model/metadata`, `GET /api/health`. Le choix d'**ajouter** ces routes plutôt que
de renommer `POST /api/scan` préserve le frontend, les tests et la documentation
existants ; les deux noms apparaissent séparément dans Swagger.

### 2.1 `GET /api/health`

Publique, **toujours 200** tant que le processus vit, afin de rester utilisable comme
`healthcheck` de conteneur : des modèles absents sont signalés par `present: false`, pas
par une erreur. Elle lit uniquement `models/models.json` et le contenu du dossier, donc
interroger la santé **ne charge jamais les 33 Mo de poids**.

Réponse réelle sur la machine de développement :

```json
{ "status": "ok", "api_version": "0.2.0", "gpu": false,
  "providers": { "available": ["AzureExecutionProvider", "CPUExecutionProvider"],
                 "requested": "cpu", "gpu": false },
  "models_loaded": false,
  "models": {
    "detect":   { "file": "detector.onnx",   "present": true,
                  "registered_model": "tujya-pill-detector",   "version": 1,
                  "run_id": "351bf9233a214f78ac0a3deab83959e0" },
    "classify": { "file": "classifier.onnx", "present": true,
                  "registered_model": "tujya-pill-classifier", "version": 1,
                  "run_id": "9e118a986ca8420383754100514d54a1" } },
  "models_published_at": "2026-11-01T19:19:56+00:00" }
```

Les trois éléments demandés par le guide y sont : **état du serveur** (`status`),
**présence du GPU** (`gpu`, déduit des execution providers d'ONNX Runtime) et **version du
modèle chargé** (`version` et `run_id` MLflow de chacun des deux modèles).

### 2.2 `GET /api/model/metadata`

Publique, comme `/api/health` : elle ne décrit aucune donnée d'utilisateur. Elle retourne,
pour chacun des deux modèles servis :

- l'**architecture lue dans les métadonnées ONNX du fichier** (`YOLO11n`,
  `YOLO11s-cls`) — elle n'est pas écrite en dur, elle vient du fichier réellement servi ;
- la version d'Ultralytics qui a produit l'export, les formes des tenseurs d'entrée et de
  sortie (`[1,3,640,640] → [1,5,8400]` et `[1,3,224,224] → [1,150]`), le nombre de classes ;
- le modèle enregistré MLflow, sa version et son `run_id` ;
- les **paramètres d'entraînement** et les **métriques de validation** de ce run ;

puis, pour le pipeline : les 150 classes avec leur nom, le seuil de confirmation, les
scores bout‑en‑bout, les execution providers disponibles et l'avertissement d'usage.

**Point de rigueur.** Les métriques sont indexées par `run_id` MLflow dans
`backend/app/model_card.py`. Publier une version de modèle absente de cette table renvoie
`validation_metrics: {}` : l'API préfère ne rien affirmer plutôt que d'attribuer à un
fichier les scores d'un run précédent. Un test automatisé vérifie ce comportement.

Réponse `503` lorsque les fichiers ONNX ne sont pas dans le dossier des modèles.

### 2.3 `POST /api/predict`

Même gestionnaire que `POST /api/scan` : un fichier image (`UploadFile`), le
prétraitement complet (letterbox, NMS, recadrage carré à 20 % de marge) et une prédiction
structurée en JSON — par comprimé : la boîte en pixels et en coordonnées normalisées, la
confiance de détection, les 5 classes les plus probables avec leurs principes actifs, et
`needs_confirmation`.

### 2.4 `POST /api/predict/visualize`

La même inférence rendue en **image PNG** au lieu de JSON : une boîte par comprimé, d'une
couleur dérivée de l'identifiant de classe (un même produit garde toujours la même
couleur, deux produits différents dans une photo ne la partagent jamais), légendée par le
produit le plus probable et sa probabilité, suivie de « (to confirm) » sous le seuil. Un
bandeau rappelle le nombre de comprimés et le temps d'inférence, également exposés dans les
en‑têtes `X-Pills` et `X-Inference-Ms`.

Vérification sur une photo réelle du split de test C3PI (jamais vue à l'entraînement) :
`200 image/png`, `X-Pills: 1`, `X-Inference-Ms: 646`, boîte correcte sur
**LABETALOL HYDROCHLORIDE à 96,5 %**. Le rendu est en pur OpenCV
(`backend/app/annotate.py`), sans dépendance supplémentaire.

### 2.5 Gestion des erreurs : un écart assumé

| Situation | Guide | Tujya | Justification |
|---|---|---|---|
| Modèle non instancié | `503` | `503` | conforme |
| Fichier trop volumineux | — | `413` | refusé sur `Content-Length`, avant lecture du corps |
| Fichier qui n'est pas une image | `400` | **`415`** | voir ci‑dessous |

`415 Unsupported Media Type` est le code que la RFC 9110 définit exactement pour un corps
dont le type de média n'est pas accepté ; `400` désigne une requête malformée. Le frontend
et trois tests automatisés s'appuient sur `415`, et le message d'explication est identique
dans les deux cas. L'écart est documenté dans `docs/API.md` ; il se corrige en une ligne si
le jury préfère la lettre du cahier des charges.

## 3. §5.2 — Frontend

| Exigence du guide | État | Où |
|---|---|---|
| React ou Angular | **Conforme** — React 19 + TypeScript + Vite | `frontend/package.json` |
| Glisser‑déposer depuis le disque | **Conforme** | `ScanPage.tsx` (`onDrop`, `dragOver`) |
| Galerie d'exemples préchargés, inférence en 1 clic | **Conforme** | `GET /api/demo/images` |
| Webcam (capture ou flux continu) | **Conforme** | `getUserMedia`, ~1 image/s, non journalisée |
| Boîtes englobantes, couleurs distinctes par classe | **Conforme** | canvas React ; côté API `/predict/visualize` |
| Scores en barres de progression | **Conforme** | top‑5 avec probabilités |
| Latence en ms, client **et** serveur | **Conforme** | `timings` (`detection_ms`, `classification_ms`, `total_ms`) |
| **Framework CSS** (Tailwind, Material UI, Shadcn/UI…) | **Écart** | CSS écrit à la main, `frontend/src/styles.css` (6 794 lignes) |

Le seul écart est le framework CSS : l'interface est stylée à la main, avec une scène 3D
`three.js` en page d'accueil, plutôt qu'avec une bibliothèque de composants. Le guide cite
ces bibliothèques comme moyen d'obtenir une « UX moderne » ; le critère noté en §8 est
« frontend ergonomique, réactif et esthétique », qui est atteint par un autre chemin. À
signaler spontanément en soutenance plutôt qu'à laisser découvrir.

## 4. §5.3 — Cycle MLOps

### 4.1 DVC

`dvc.yaml` + `dvc.lock` au niveau du dépôt, deux étapes reproductibles : `prepare`
(construction des jeux de détection et de classification depuis les photos C3PI) et
`rag_corpus`. Les données et les poids sont exclus de Git par `.gitignore` : `data/**`,
`/models/`, `mlruns/`, `mlartifacts/`, `*.onnx`, `*.pt`.

*Réserve :* aucun remote DVC n'est configuré : le cache (4,7 Go) n'existe que sur ce PC.
Le réglage `no_scm = true` (DVC sans Git) a été retiré de `.dvc/config.local` le 2026‑11‑22,
une fois le dépôt Git restauré (§7.1).

### 4.2 MLflow — tracking et Model Registry

Serveur **construit par le dépôt** (`docker/mlflow/Dockerfile`, `mlflow==3.17.2` +
`psycopg2`), lancé par Docker Compose, interface sur `http://localhost:5000` :

- **backend store** : base PostgreSQL dédiée `mlflow`, créée au premier démarrage par
  `docker/postgres/init/01-init.sql` ;
- **artefacts** : volume `mlartifacts`, servis par le serveur (`--serve-artifacts`) ;
- tous les ports publiés sur `127.0.0.1` uniquement.

Quatre expériences sont déclarées dans le code — `tujya-vision`, `tujya-tox`,
`tujya-synergy`, `tujya-rag` — chaque script appelant
`mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))`.

**Statut du meilleur modèle.** Exigence explicite du guide, mise en place le 2026‑11‑17 :

| Modèle enregistré | Version | Stage | Alias | Run |
|---|---|---|---|---|
| `tujya-pill-detector` | 1 | `Production` | `@production` | `351bf9233a21…` |
| `tujya-pill-classifier` | 1 | `Production` | `@production` | `9e118a986ca8…` |
| `tujya-tox21` | 1 | `Production` | `@production` | `a3363bbba4f2…` |

Le *stage* et l'*alias* sont posés tous les deux : MLflow 3 met l'alias en avant, le stage
reste lisible dans l'ancienne vue. Les trois `run_id` sont **exactement** ceux inscrits
dans `models/models.json` et renvoyés par `GET /api/health` : ce qui est marqué
« Production » dans le registre est bien ce que l'API sert. La procédure est dans
`docs/VISION.md`.

### 4.3 Optimisation du modèle : ONNX + ONNX Runtime

Les deux modèles sont exportés en ONNX par `vision/tujya_vision/train.py`, qui vérifie
ensuite ONNX Runtime contre PyTorch sur les images de test (accord top‑1 **100 %**, écart
maximal de probabilité 1,5·10⁻⁶ ; même nombre de boîtes, IoU moyenne **0,992**).

L'API ne dépend **ni de PyTorch ni d'Ultralytics** : `backend/app/scanner.py` réimplémente
le letterbox, la NMS et le recadrage en numpy + OpenCV et exécute les deux fichiers ONNX.
Contrôle de non‑régression : sur les 600 photos de test, comprimé trouvé 98,5 %, top‑1
**89,3 %**, top‑5 95,8 % — identiques à l'évaluation bout‑en‑bout faite avec Ultralytics.

### 4.4 Conteneurisation

`docker compose up -d` lance **huit services** : `postgres` (pgvector/pg16), `mlflow`,
`pharma-init` (recharge les tables médicaments puis sort), `chroma`, `rag-init`, `backend`,
`ollama`, `frontend` ; quatre volumes nommés. Tous les ports publiés sont liés à
`127.0.0.1`.

| | Multi‑stage | Détail |
|---|---|---|
| `frontend/Dockerfile` | **Oui** | `node:22-alpine AS build` → `nginx:1.27-alpine` |
| `backend/Dockerfile` | **Non** | une seule étape `python:3.12-slim` |

Le guide demande des Dockerfile multi‑stage pour **les deux**. L'écart subsiste côté
backend (§7.2).

### 4.5 CI/CD GitHub Actions

Deux workflows sont spécifiés dans `docs/CD.md` :

| Workflow | Déclenchement | Contenu |
|---|---|---|
| `ci.yml` | chaque push et chaque pull request | lint et tests unitaires du pipeline, du backend et du paquet vision ; vérification de types et build du frontend |
| `cd.yml` | `workflow_run` après un `ci` vert sur `main`, ou manuel | build Buildx des deux images, test de fumée (`/api/health`, `/docs`, présence de `/api/scan` et `/api/chat` dans `/openapi.json`), **sans publication** |

Les deux workflows sont dans le dépôt (`.github/workflows/`), restaurés le 2026‑11‑22 dans
la copie de travail (§7.1).

### 4.6 Tests automatisés

**198 tests backend** collectés et au vert (`backend/tests/`), dont 17 ajoutés le
2026‑11‑17 pour les points d'entrée du cahier des charges : santé publique et sans
chargement des poids, carte de modèle avec et sans tables médicaments, refus d'inventer des
métriques pour un run inconnu, équivalence `/api/predict` ↔ `/api/scan`, présence des
quatre chemins dans `/openapi.json`, PNG annoté et ses en‑têtes, erreurs 401/415/503, et
tests unitaires du rendu (couleurs distinctes sur 150 classes, image non modifiée en
place). S'y ajoutent des tests de fumée Playwright (`frontend/tests/`) et `tests/live/`.

Qualité du code : `ruff` (lint + format, 100 colonnes), `mypy`, et `.pre-commit-config.yaml`
qui exécute entre autres `detect-private-key`, `check-added-large-files` et les tests
unitaires avant chaque commit.

## 5. §6 — Arborescence

L'arborescence du guide est respectée dans son principe — séparation données / code DL /
backend / frontend / orchestration — avec une organisation plus riche imposée par le
périmètre réel du projet (deux modules, trois familles de modèles) :

| Guide | Tujya | Remarque |
|---|---|---|
| `data/raw`, `data/processed` | `data/` (versionné DVC, hors Git) | identique |
| `src/` (code DL & MLOps) | `vision/tujya_vision/` + `src/synergyrx_data/` | vision séparée du pipeline de données |
| `src/models/train.py`, `evaluate.py` | `vision/tujya_vision/{train,evaluate,publish}.py` | `publish.py` en plus : registre → `models/` |
| `backend/app/{main,schemas,inference}.py` | `backend/app/` (`main.py`, `schemas.py`, `scanner.py`, `routers/`) | `scanner.py` tient le rôle de `inference.py` |
| `backend/tests/test_api.py` | `backend/tests/` (19 fichiers de tests, 198 tests) | plus fin |
| `frontend/src/{components,services}` | `frontend/src/{pages,api.ts,components.tsx}` | équivalent |
| `docker-compose.yml`, `dvc.yaml`, `README.md` | présents à la racine | identique |
| `rapport_technique.pdf` (racine) | `docs/rapports/` | voir §7.4 |

## 6. §8 — Barème : auto‑évaluation

| Dimension | Barème | Appréciation appuyée sur |
|---|---|---|
| **1. Modélisation DL & rigueur scientifique** | 6,0 | Transfer learning COCO/ImageNet ; baseline *smoke* YOLO11n‑cls (19,4 %) comparée au modèle final YOLO11s‑cls (**93,9 %**) ; métriques adaptées (mAP50‑95, top‑1/top‑5, ROC‑AUC) ; export ONNX vérifié contre PyTorch ; **étiquetage automatique assumé et audité** (décision D38, ~90 % de boîtes correctes sur un échantillon de 48 photos) ; seuil de confirmation 0,85 choisi sur la validation par une règle posée d'avance |
| **2. Cycle MLOps & reproductibilité** | 5,0 | DVC (2 étapes, `dvc.lock`) ; MLflow tracking + Registry avec **stage Production et alias** ; ONNX Runtime ; Compose à 8 services en une commande ; CI/CD GitHub Actions (`ci.yml`, `cd.yml`) ; Dockerfile backend mono‑étape (§7.2) |
| **3. Solution full‑stack** | 5,0 | FastAPI asynchrone, Pydantic strict, Swagger ; 37 chemins documentés ; React 19 + Vite, trois modes d'ingestion, boîtes, scores, latences ; écart framework CSS (§3) |
| **4. Rapport & documentation** | 2,0 | 25 fichiers dans `docs/`, deux rapports de module, `DECISIONS.md` traçant les choix (D38…D86), README d'installation ; **rapport LaTeX racine manquant** (§7.4) |
| **5. Soutenance technique** | 2,0 | Démonstration possible en direct : Compose, Swagger, MLflow sur `:5000`, revue de code |

## 7. Écarts restants, par impact

### 7.1 Dépôt Git : restauré, historique à équilibrer

La copie du projet d'un disque à l'autre avait perdu `.git`, `.github/`, `tests/unit/`, une
partie de `src/synergyrx_data/` (`http/cache.py`, `http/circuit.py`, `export/`) et
`backend/app/accounts.py`. **Résolu le 2026‑11‑22** : le dossier est rattaché au dépôt
`mohamedraedbouhali/Tujya-1`, les fichiers perdus ont été restaurés depuis ce dépôt (dont
l'`accounts.py` d'origine, qui remplace la version reconstruite : 198 tests backend au vert).
À l'inverse, le premier push n'avait pas inclus `vision/tujya_vision/`, `vision/tests/` ni
`.dvc/config` : ils sont ajoutés.

**Reste :** l'historique distant ne compte que 5 commits, tous du même auteur ; le guide
attend des contributions équilibrées des trois membres, chacun depuis son propre compte.

### 7.2 `backend/Dockerfile` mono‑étape

Le §5.3 exige des Dockerfile multi‑stage pour le frontend **et** le backend. Le frontend
l'est ; le backend installe et exécute dans la même étape `python:3.12-slim`.

**Action :** étape *builder* qui compile les roues, étape d'exécution qui ne copie que le
`site-packages` nécessaire.

### 7.3 Deux expériences MLflow absentes du serveur

Le serveur en service ne contient que `tujya-vision` (3 runs) et `tujya-tox` (1 run).
`tujya-synergy` et `tujya-rag` sont déclarées dans le code mais n'ont jamais été rejouées
sur cette machine : les chiffres correspondants dans la documentation n'ont donc pas de run
local derrière eux. Le §8 note explicitement la « richesse du tracking MLflow ».

**Point associé.** Il existe un second magasin de tracking, orphelin : `mlruns/mlflow.db`
(SQLite) contient un run `tujya-tox` `43a083cb…`, alors que `models/tox21/model.json`
désigne `a3363bbb…`, venu du serveur PostgreSQL. Les deux affichent les mêmes métriques
parce que l'entraînement est graine fixe (42). C'est ce qui arrive quand on entraîne sans
`MLFLOW_TRACKING_URI` et sans serveur démarré. `mlruns/` et `mlartifacts/` à la racine
peuvent être supprimés : les artefacts réels sont dans le volume Docker.

### 7.4 Pas de `rapport_technique.pdf` LaTeX à la racine

Le §6 place un `rapport_technique.pdf` rédigé en LaTeX à la racine, et le §8 note
« rapport rédigé en LaTeX ». Le dépôt contient `docs/rapports/rapport_module1_vision_mlops.{md,pdf}`
et `rapport_module2_ai_engineering.md`, plus des notes explicatives sous
`reports/explicatifs/`.

### 7.5 Framework CSS

Voir §3. Écart mineur, à mentionner spontanément.

## 8. Les « 5 erreurs critiques » du guide (§9)

| Erreur | Statut |
|---|---|
| 1. *Notebook‑only syndrome* | **Évitée.** API FastAPI, frontend React et Compose fonctionnels ; aucun notebook dans la chaîne de production |
| 2. Données ou poids commités dans Git | **Évitée.** `data/**`, `/models/`, `*.onnx`, `*.pt`, `mlruns/`, `mlartifacts/` dans `.gitignore` ; DVC pour les données ; `detect-private-key` et `check-added-large-files` en pre‑commit |
| 3. Fuite de données | **Évitée, et documentée.** Vision : une photo et **tous ses recadrages** restent dans le même split, décidé avant l'entraînement. Tox21 : split par squelette de Bemis‑Murcko, comme MoleculeNet/DeepChem, pas un split aléatoire |
| 4. Interface « coquille vide » | **Évitée.** Boîtes dessinées, barres de probabilité, latences affichées, galerie, webcam |
| 5. Absence de tests automatisés | **Évitée.** 198 tests backend au vert, plus Playwright et `tests/live/` ; exécutés en pre‑commit et en CI |

## 9. Démonstration en soutenance (§9, 15–20 min)

1. **Démonstration en direct (5 min)** — `docker compose up -d`, puis `http://localhost:8080` :
   glisser‑déposer une photo, galerie, webcam ; boîtes, top‑5, temps de réponse ; vérification
   d'interactions. Swagger sur `http://localhost:8000/docs` pour `GET /api/model/metadata` et
   `POST /api/predict/visualize`, qui renvoie l'image annotée directement dans le navigateur.
2. **Revue MLOps (5 min)** — MLflow sur `http://localhost:5000` : expériences, comparaison des
   runs, onglet *Models* montrant les trois modèles en **Production**, et correspondance des
   `run_id` avec `GET /api/health`. Puis `dvc.yaml` / `dvc.lock`, et l'état des workflows
   GitHub Actions.
3. **Revue de code (5–10 min)** — `backend/app/scanner.py` (letterbox, NMS, recadrage sans
   PyTorch), `backend/app/model_card.py` (métriques indexées par `run_id`),
   `vision/tujya_vision/autolabel.py` (étiquetage automatique, décision D38),
   `backend/app/annotate.py`, et `docs/DECISIONS.md` pour la traçabilité des choix.

---

*Sources : le dépôt au 2026‑11‑17 ; `models/models.json` ; `vision/runs/*/summary.json` ;
le serveur MLflow interrogé par son API REST ; appels réels aux points d'entrée avec les
modèles publiés ; `docs/VISION.md`, `docs/API.md`, `docs/CD.md`, `docs/INFRA.md`,
`docs/TOXICITY.md`, `docs/DECISIONS.md`.*
