# SATISFY restock monitor

Bot de surveillance de réapprovisionnement (restock) pour les produits
[SATISFY Running](https://satisfyrunning.com), par défaut le **HeatCrush Muscle
Tee (Moonstruck)**. Il tourne gratuitement via **GitHub Actions** et envoie une
notification push sur ton téléphone via **[ntfy.sh](https://ntfy.sh)** dès qu'une
variante repasse de *indisponible* à *disponible*.

> 💡 **Compte GitHub bloqué / pas envie d'Actions ?** Une version 100% gratuite
> tournant sur **Google Apps Script** (aucune carte, ton compte Google) est
> fournie dans [`apps-script/`](apps-script/) — même logique, notifs ntfy
> identiques.

## Comment ça marche

À chaque exécution, [`check.py`](check.py) :

1. Récupère la disponibilité **par variante** via une cascade Shopify robuste :
   `{url}.js` → `{url}.json` → regex HTML sur `"available":true/false`.
2. Compare avec l'état précédent stocké dans [`state.json`](state.json).
3. N'envoie une alerte ntfy **que** sur la transition
   `indisponible → disponible` (aucun spam au premier passage ni tant que
   l'article reste dispo).
4. Réécrit `state.json`, que le workflow recommite dans le repo pour garder la
   mémoire entre deux runs.

Un échec réseau/format sur un produit **ne réinitialise pas** son état (pas de
fausse alerte, pas de perte de mémoire).

## Configuration

Le script se pilote entièrement par variables d'environnement :

| Variable       | Rôle                                                        | Défaut |
| -------------- | ----------------------------------------------------------- | ------ |
| `PRODUCT_URLS` | URLs produit séparées par des virgules (multi-produits).    | HeatCrush Muscle Tee (Moonstruck) |
| `NTFY_TOPIC`   | Topic ntfy.sh où poster les alertes. **Requis** pour notifier. | *(vide → dry-run)* |
| `NTFY_SERVER`  | Serveur ntfy.                                               | `https://ntfy.sh` |
| `NTFY_TOKEN`   | Jeton Bearer ntfy (topics protégés), optionnel.            | *(vide)* |
| `STATE_FILE`   | Chemin du fichier d'état.                                   | `state.json` |
| `USER_AGENT`   | User-Agent HTTP.                                            | UA navigateur |

## Installation (GitHub Actions)

1. **Choisis un topic ntfy** difficile à deviner, ex. `satisfy-restock-8f3k2p`.
2. Installe l'app ntfy ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) /
   [iOS](https://apps.apple.com/us/app/ntfy/id1625396347)) et **abonne-toi à ce
   topic**.
3. Dans le repo GitHub → **Settings → Secrets and variables → Actions** :
   - Onglet **Secrets** → `New repository secret` :
     `NTFY_TOPIC` = ton topic (et `NTFY_TOKEN` si ton topic est protégé).
   - Onglet **Variables** (optionnel) :
     `PRODUCT_URLS` = liste d'URLs si tu veux surveiller autre chose ou
     plusieurs produits ; `NTFY_SERVER` si tu auto-héberges ntfy.
4. Le workflow [`.github/workflows/restock.yml`](.github/workflows/restock.yml)
   tourne toutes les 15 min. Lance-le une première fois à la main via
   **Actions → SATISFY restock monitor → Run workflow** pour initialiser l'état.

> ⚠️ Le planificateur cron de GitHub Actions est *best-effort* : les exécutions
> peuvent être décalées ou groupées en période de forte charge. 15 min est un
> bon compromis pour ne pas se faire limiter par Shopify.

## Test en local

```bash
pip install requests

# Dry-run (aucune notification, juste les logs de dispo) :
python check.py

# Avec notifications :
NTFY_TOPIC="satisfy-restock-8f3k2p" python check.py

# Plusieurs produits :
PRODUCT_URLS="https://satisfyrunning.com/products/heatcrush-muscle-tee-moonstruck,https://satisfyrunning.com/products/autre-produit" \
  python check.py
```

Pour simuler un restock : mets une variante à `"available": false` dans
`state.json`, relance le script alors qu'elle est réellement dispo → tu reçois
l'alerte.
