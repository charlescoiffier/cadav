# Cadavre exquis en terminal — Cahier des charges v1 (révision 5)

## 1. Objectif
Jeu de cadavre exquis textuel multijoueur, joué dans le terminal via une TUI. Un serveur central gère le lobby et toutes les parties. Les joueurs s'inscrivent (très léger), créent ou rejoignent des parties en attente de joueurs, et écrivent à tour de rôle une histoire commune.

## 2. Arbitrages retenus

| Sujet | Décision v1 |
|-------|-------------|
| Déroulement | **Une seule histoire, tours séquentiels** : un seul joueur écrit à la fois, après avoir vu l'amorce laissée par le précédent |
| Ordre des joueurs | Tiré au sort au lancement |
| Amorce | Dernière phrase de la contribution précédente ; paramétrable à la création (voir §4) |
| Contenu | Texte libre, thème facultatif défini à la création et affiché à tous |
| Taille d'une partie | 3 à 8 joueurs, un tour par joueur |
| Contribution | Limites basse et haute en nombre de mots, facultatives, réglées par l'hôte. Pas de filtre de contenu |
| Échéance de tour | Un seul paramètre par partie (voir §5). Pas de « mode » distinct |
| Tour sauté | À l'échéance, le joueur est sauté : le suivant voit la même amorce, et l'histoire compte une contribution de moins |
| Révélation finale | Texte complet affiché d'un coup |
| Visibilité | Publique (liste) ou privée (code) |
| Lancement | Automatique quand le nombre de joueurs souhaité est atteint, ou par l'hôte avant (minimum 3 joueurs) |
| Identité | Pseudo + secret local, sans mot de passe |
| Persistance | Fichiers JSON, écriture atomique, pas de base de données |
| Parties par joueur | Plusieurs en parallèle, plafond de 5 parties actives par pseudo |
| Code | Un seul paquet : `cadavre play` (client) et `cadavre serve` (serveur) |
| Langue | Interface en français pour l'instant |
| Export | Copie dans le presse-papiers et export `.txt` / `.md` depuis l'écran final |

## 3. Pile technique
- Python 3.11+
- Serveur : `asyncio` + `websockets`
- Client : Textual
- Messages : Pydantic, dans un module partagé client/serveur
- Distribution : paquet installable avec `pipx`
- Tests : `pytest` + `pytest-asyncio`

## 4. Règles du jeu
- Au lancement, l'ordre des joueurs est tiré au sort.
- Tour 1 : page blanche (le thème, s'il existe, est affiché).
- Tours suivants : le joueur ne voit que l'**amorce** tirée de la contribution précédente. Il ne voit jamais le reste de l'histoire.
- Réglage d'amorce à la création : `dernière phrase` (défaut), `N derniers mots`, ou `aucune`.
  - Dernière phrase : détectée à la ponctuation (`. ! ? …`), guillemets fermants tolérés après le point (`« Non. » Il part.` → `Il part.`). Si la contribution n'a pas de ponctuation finale, on prend les 12 derniers mots.
  - `N derniers mots` : N est le paramètre `primer_words` (1 à 100, défaut 12).
- Tour sauté (échéance dépassée) ou joueur parti : la contribution n'existe pas, le joueur suivant reçoit la même amorce.
- Après le dernier tour, la partie passe à `finished` et l'histoire complète est révélée à tous, avec chaque contribution attribuée à son auteur.
- Quitter signifie uniquement l'action explicite `leave_game` : se déconnecter ou être absent n'est pas un départ (le joueur est simplement sauté à l'échéance de son tour, et garde l'accès à la partie).
- La partie se termine et révèle ce qui existe dès qu'il ne reste plus aucun joueur ayant un tour à venir ou en cours. Un joueur qui a déjà écrit, ou qui a été sauté, ne maintient donc pas la partie en vie. Un unique joueur restant peut finir seul son tour.
- Un joueur qui quitte une partie en cours garde l'attribution de ses contributions déjà écrites, perd l'accès à la partie, et son tour (à venir ou en cours) est passé sans compter comme « sauté ». Son départ pendant son tour passe la main avec la même amorce.
- Chaque joueur a exactement un tour : un tour sauté n'est jamais rejoué. La partie finit après le tour du dernier joueur de l'ordre.

## 5. Échéances
- Un paramètre unique à la création : l'**échéance par tour**, de 30 s à 72 h.
- Proposés dans le formulaire : « Rapide » (2 min), « Tranquille » (24 h), ou valeur personnalisée.
- L'échéance est un horodatage UTC absolu enregistré dans l'état de la partie. Une tâche `asyncio` est planifiée par échéance et replanifiée au redémarrage du serveur.
- Une salle d'attente inactive expire (15 min si l'échéance est inférieure à 1 h, sinon 48 h).

## 6. Identité
- Premier lancement : le client génère un secret aléatoire (32 octets), le stocke dans sa config locale et envoie `register {pseudo, secret}`.
- Le serveur enregistre `pseudo -> {sel, hash}` dans `data/users.json` (pseudo unique, insensible à la casse) et compare en temps constant. Le secret étant 32 octets aléatoires et non un mot de passe humain, le hash est un SHA-256 salé, sans étirement de clé. Pseudo : 2 à 24 caractères (lettres, chiffres, `_`, `-`).
- Connexions suivantes : `auth {pseudo, secret}`. Une seule connexion WebSocket par pseudo : une nouvelle remplace l'ancienne.
- Limitation par IP : 20 inscriptions ou échecs de connexion par fenêtre de 10 minutes (erreur `too_many_attempts`) ; TLS obligatoire dès que le serveur est public.
- Limite connue : config perdue = pseudo perdu ; changement d'appareil par copie du fichier de config.

## 7. Cycle d'une partie
États : `waiting -> running -> finished` (ou `expired`).
- **Création** : `create_game {visibilité, joueurs_souhaités (3 à 8), échéance, thème?, amorce, mots_min?, mots_max?}`. Le serveur génère un code de 5 lettres sans caractères ambigus (pas de O/0, I/1) et désigne le créateur comme hôte.
- **Rejoindre** : `join_game {id | code}`. Refus si partie pleine, lancée, ou plafond de 5 parties atteint.
- **Lancement** : automatique à `joueurs_souhaités`, ou `start_game` par l'hôte (minimum 3). Les réglages sont regroupés dans un objet `settings` (`visibility`, `desired_players`, `turn_seconds`, `theme`, `primer_mode`, `primer_words`, `min_words`, `max_words`).
- **Plafond de 5 parties actives par pseudo** et unicité du code : contrôlés par le serveur (jalon 2), qui voit toutes les parties ; `game.py` ne gère qu'une partie.
- **Hôte** : s'il part en salle d'attente, le rôle passe au plus ancien joueur. Salle vide : partie supprimée.
- **Écriture** : `submit_text {game_id, texte}`, accepté seulement du joueur dont c'est le tour, dans les limites de mots.

## 8. Protocole
Chaque message : `{v, type, game_id?, ...}`. Tout message de partie porte un `game_id`, et le serveur vérifie l'appartenance du joueur. Le numéro de version `v` (actuellement 1) permet de refuser un client trop ancien (erreur `unsupported_version`). Les champs inconnus d'un message client sont refusés. `join_game` prend exactement un de `game_id` ou `code`.

Les événements serveur (`game_joined`, `player_joined`, `player_left`, `game_started`, `turn_started`, `turn_skipped`, `game_finished`) portent la projection `view` (voir §9) propre au destinataire. Le message `error` porte `code` (stable, pour le client) et `message` (français, affichable tel quel). `lobby_update` porte des `LobbyEntry` (sans code, sans texte) ; il est envoyé en réponse à `list_games`, puis poussé à chaque changement des parties publiques en attente aux clients qui ont fait `list_games`. Les parties privées n'y figurent jamais et ne se rejoignent que par code.

Pas de message dédié à l'expiration d'une salle d'attente : le serveur envoie `error` avec `code: "game_expired"` et le `game_id`. Après `leave_game`, le serveur renvoie `my_games` au joueur qui part (accusé de réception). Remplacement de connexion : l'ancienne est fermée avec le code WebSocket 4000 ; version refusée : 4001.

- Client vers serveur : `register`, `auth`, `list_games`, `create_game`, `join_game`, `leave_game`, `start_game`, `submit_text`.
- Serveur vers client : `auth_ok`, `my_games`, `lobby_update`, `game_joined`, `player_joined`, `player_left`, `game_started`, `turn_started`, `turn_skipped`, `game_finished`, `error`.

## 9. Confidentialité de l'état
- Le serveur garde l'état complet. Le client ne reçoit jamais le JSON complet.
- `view_for(game, pseudo)` produit la projection par joueur :
  - salle d'attente : joueurs, options, thème, code, hôte ;
  - en cours : ordre des joueurs, de qui c'est le tour, échéance ; le joueur dont c'est le tour reçoit en plus l'amorce ; aucun autre texte ;
  - après `finished` : l'histoire complète.
- Cette projection sert à `my_games` (connexion et reprise) puis aux événements.
- Un non-membre ne peut obtenir la projection que d'une partie publique en attente ; un joueur qui a quitté n'a plus de projection.
- Test obligatoire : la projection d'un joueur ne contient jamais de texte autre que son amorce avant la fin.

## 10. Persistance
- `data/users.json` : comptes.
- `data/games/<id>.json` : parties en cours, réécrites à chaque changement d'état.
- `data/archive/<date>-<id>.json` : parties terminées. Une partie terminée reste en mémoire 7 jours (et est rechargée depuis l'archive au démarrage) : un joueur absent à la fin retrouve l'histoire dans `my_games` à sa reconnexion. Les archives restent sur disque.
- Écriture atomique (fichier temporaire puis `os.replace`). Rechargement et replanification des échéances au démarrage.

## 11. Interface (Textual)
- **Lobby** : section « Mes parties » (badge « À toi »), liste des parties publiques, saisie d'un code, bouton « Créer ».
- **Création** : formulaire (visibilité, joueurs souhaités, échéance, thème, amorce, limites de mots).
- **Salle d'attente** : joueurs en direct, code affiché, bouton « Lancer » pour l'hôte.
- **Partie** : thème, de qui c'est le tour, échéance, amorce, zone de saisie avec compteur de mots (quand c'est ton tour).
- **Écran final** : histoire complète, copie et export.
- Navigation entre parties par raccourci ; bandeau discret pour les événements des autres parties.
- Configuration locale : pseudo, secret, URL du serveur.

## 12. Limites et sécurité
- Taille maximale des messages WebSocket ; plafond technique de 2000 caractères par contribution.
- Nombre maximal de parties simultanées sur le serveur (1000 en attente ou en cours), et 10 créations par pseudo par heure. Messages WebSocket limités à 64 Ko.
- Chaque partie tourne dans sa propre tâche avec gestion d'erreur isolée.
- Nettoyage des parties expirées.

## 13. Structure du dépôt
```
cadavre/
  protocol.py      # messages Pydantic partagés
  game.py          # logique pure (ordre, tours, amorce, view_for) ; heure et rng injectés
  server.py        # WebSocket, lobby, échéances
  storage.py       # JSON atomique (users, games, archive)
  client/          # app Textual : app.py, screens.py, connection.py, config.py, logic.py
  cli.py           # cadavre play | cadavre serve
tests/
```
La logique de jeu reste pure (sans réseau ni disque), donc testable seule.

## 14. Jalons
1. `protocol.py` + `game.py` + tests (ordre, tours sautés, extraction d'amorce, projection, échéances). **Fait (53 tests).**
2. `storage.py` + `server.py`, testés avec un client WebSocket de script. **Fait (84 tests au total).**
3. Client Textual : lobby, création, salle d'attente. **Fait (130 tests au total).**
4. Écran de partie et reprise à la connexion.
5. Écran final, export, packaging `pipx`.
6. Déploiement sur VPS (WSS) et essais en conditions réelles.

## 15. Après la v1
Notifications push (ntfy.sh ou webhook), i18n. Idées plus lointaines : mode guidé (qui, quoi, où), plusieurs tours par joueur, SQLite, statistiques, amis.

## 16. Décisions d'implémentation (jalon 1)
- `game.py` expose des fonctions qui modifient une `Game` (modèle Pydantic sérialisable, c'est le format de `data/games/<id>.json`) et renvoient la liste d'événements à diffuser (`PlayerJoined`, `GameStarted`, `TurnStarted`, `TurnSkipped`, `GameFinished`, `GameDeleted`, `GameExpired`…). Les erreurs de règle sont des `GameError(code, message)`.
- L'heure `now` (UTC, avec fuseau) et le `random.Random` sont toujours passés en argument.
- Échéances : `expire_turn(game, now)` et `expire_waiting(game, now)` sont idempotents et sans effet avant l'échéance ; le serveur les appelle depuis ses tâches `asyncio`. L'expiration d'une salle d'attente se compte depuis la dernière activité (arrivée ou départ).
- Salle d'attente vidée : `leave` renvoie `GameDeleted` ; c'est au serveur de supprimer la partie.
- Code de partie : 5 lettres parmi `ABCDEFGHJKLMNPQRSTUVWXYZ` (pas de chiffres, ni I ni O).
- Dépendances : `pydantic` seul pour le jalon 1 ; `websockets` et `textual` arriveront avec les jalons 2 et 3.
- Environnement de dev : `uv venv .venv && uv pip install -e '.[dev]'`, puis `.venv/bin/pytest`.

## 17. Décisions d'implémentation (jalon 2)
- `server.py` sépare le transport de la logique : la classe `Server` travaille sur des objets `Session` (fonctions `send` et `close`) ; seul `Server.listen()` utilise `websockets`. L'horloge, le générateur aléatoire et les limites (`Limits`) sont injectés.
- Une `asyncio.Task` par échéance (tour en cours ou salle d'attente), recréée à chaque changement d'état de la partie, et réarmée au démarrage (`Server.start`) : une échéance déjà dépassée se déclenche aussitôt. `check_deadlines()` applique à la demande toutes les échéances passées.
- Chaque changement est écrit sur disque avant d'être oublié ; une erreur d'écriture est journalisée sans faire tomber la partie. Un fichier de partie illisible est ignoré au démarrage.
- Les parties terminées passent de `data/games/` à `data/archive/` ; une salle vidée ou expirée est supprimée.
- Un `leave_game` ou `submit_text` d'un non-membre renvoie `not_in_game`, sans révéler si la partie existe.
- Lancement du serveur pour essai : `.venv/bin/python -m cadavre.server --port 8765 --data-dir data` (options `--cert` et `--key` pour TLS). La commande `cadavre serve` arrive avec `cli.py` (jalon 5).
- Dépendance ajoutée : `websockets` (prévue au §3).

## 18. Décisions d'implémentation (jalon 3)
- Le client est un paquet `cadavre/client/` : `logic.py` (analyse du formulaire et textes, sans Textual ni réseau, testé seul), `config.py`, `connection.py` (WebSocket), `screens.py` et `app.py`. Lancement provisoire : `.venv/bin/python -m cadavre.client [--url ws://…] [--config fichier]` ; la commande `cadavre play` arrive avec `cli.py` (jalon 5).
- Configuration locale : `~/.config/cadavre/config.json` (ou `$XDG_CONFIG_HOME`, ou `$CADAVRE_CONFIG`), contenant `pseudo`, `secret` (64 caractères hexadécimaux) et `url` ; écrite de façon atomique avec les droits `0600`. URL par défaut : `ws://localhost:8765`.
- Premier lancement : écran de connexion (pseudo + serveur) ; le secret est généré à ce moment et n'est enregistré qu'une fois l'inscription acceptée. Un secret refusé par le serveur ramène à l'écran de connexion ; saisir le même pseudo réutilise le secret stocké, un autre pseudo crée un nouveau compte.
- Reconnexion automatique (1, 2, 4 puis 8 s) avec ré-authentification ; pas de reconnexion si la connexion a été remplacée par un autre terminal (code 4000) ou si le client est trop ancien (code 4001).
- Le client ne garde que `games` (les projections reçues) et `lobby` ; chaque message serveur remplace la projection concernée, et l'écran affiché se met à jour.
- Durée d'un tour : « Rapide » (2 min), « Tranquille » (24 h) ou saisie libre (`90s`, `10min`, `36h`, `2j` ; un nombre seul = minutes), entre 30 s et 72 h.
- Salle d'attente : code, réglages, joueurs en direct ; « Lancer » réservé à l'hôte et grisé sous 3 joueurs ; « Retour » quitte l'écran sans quitter la partie, « Quitter la partie » envoie `leave_game`.
- Une partie en cours s'affiche dans « Mes parties » (★ et « à toi ! » quand c'est le tour du joueur) ; son écran de jeu n'existe pas encore : un message le dit (jalon 4).
- Dépendance ajoutée : `textual` (prévue au §3).
