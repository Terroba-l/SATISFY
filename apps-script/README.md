# Version Google Apps Script (gratuite, sans carte)

Alternative à GitHub Actions quand ton compte GitHub est bloqué : **Google Apps
Script** exécute le bot gratuitement, avec ton compte Google, sans carte
bancaire ni serveur. Même logique que `check.py` (cascade Shopify, alerte
uniquement sur restock, état persistant), notifications via ntfy.

## Installation (5 min)

1. Va sur **https://script.google.com** → **Nouveau projet**.
2. Supprime le contenu de `Code.gs` et **colle** le contenu de
   [`apps-script/Code.gs`](Code.gs).
3. Renseigne ton **topic ntfy** — deux options :
   - Rapide : édite la ligne `NTFY_TOPIC: ''` en haut du fichier.
   - Propre : **Paramètres du projet** (⚙️) → **Propriétés du script** →
     ajoute `NTFY_TOPIC` (et si besoin `PRODUCT_URLS`, `NTFY_SERVER`,
     `NTFY_TOKEN`). Les propriétés ont priorité sur les valeurs du fichier.
4. Dans l'éditeur, sélectionne la fonction **`checkRestock`** et clique
   **Exécuter**. Autorise les accès quand Google le demande
   (UrlFetchApp = requêtes sortantes). Regarde **Exécution / Journaux** : tu dois
   voir la dispo des 5 tailles.
5. Sélectionne la fonction **`createTrigger`** → **Exécuter**. Ça planifie
   `checkRestock` **toutes les 15 minutes**. (Vérifie dans **Déclencheurs** ⏰.)
6. Installe l'app **ntfy** et **abonne-toi à ton topic**.

C'est tout. Le bot tourne désormais sur l'infra Google, gratuitement.

## Bon à savoir

- **Aucun fichier d'état à committer** : l'état est stocké dans les *Script
  Properties* du projet (persiste entre deux exécutions).
- **Quotas gratuits** : `UrlFetchApp` = 20 000 appels/jour sur compte Gmail
  perso — largement suffisant (≈ 3 requêtes/produit toutes les 15 min).
- **Tester une alerte** : exécute `resetState`, puis `checkRestock` alors qu'une
  variante est réellement dispo → tu reçois la notif.
- **Plusieurs produits** : `PRODUCT_URLS` accepte des URLs séparées par des
  virgules (comme la version Python).

## Fonctions utiles dans l'éditeur

| Fonction        | Rôle                                            |
| --------------- | ----------------------------------------------- |
| `checkRestock`  | Vérification (appelée par le déclencheur).       |
| `createTrigger` | Planifie l'exécution toutes les 15 min.          |
| `resetState`    | Efface l'état mémorisé (pour re-tester).         |
