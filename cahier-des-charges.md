# cadav, cadavre exquis en terminal — Cahier des charges v1 (révision 16)

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
| Nom | L'application s'appelle **cadav** (en minuscules) : titres, commandes (`cadav serve`, `cadav play`), paquet Python `cadav/`, dossier de configuration (`~/.config/cadav/`), données du serveur (`~/.local/share/cadav/`) |
| Code | Un seul paquet : `cadav play` (client) et `cadav serve` (serveur) |
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
Direction graphique : un vrai TUI, dans l'esprit de [Posting](https://posting.sh/) (réalisé avec Textual) : thème de base de Posting (« galaxy »), repris tel quel, et palette Solarized dark en option (`--theme solarized-dark` ou clé `theme` de la configuration) ; un thème clair pourra venir plus tard : toutes les couleurs sont dans une `Palette`, panneaux à bordure arrondie dont le titre est dans la bordure, champs de formulaire d'une ligne, pastilles de couleur pour les états, barre du haut (nom de l'écran, `pseudo@serveur ● état`), pied de page avec les raccourcis, pilotage au clavier d'abord (la souris reste possible). Pas de palette de commandes.

Modèle de navigation (accessibilité) : les flèches et `Tab` / `Maj+Tab` passent d'un élément à l'autre ; `Entrée` ou `Espace` entre dans la modification d'un champ ou d'un choix, et taper du texte ou un chiffre sur une cellule commence la saisie (elle remplace le contenu) ; `Échap` en sort en annulant, `Entrée` en sort en validant (`Espace` valide aussi un menu ouvert). Hors modification, un champ ne capte pas les flèches. Tous les raccourcis généraux du pied de page utilisent `Ctrl` (`Échap` reste la touche d'annulation).

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
cadav/
  protocol.py      # messages Pydantic partagés
  game.py          # logique pure (ordre, tours, amorce, view_for) ; heure et rng injectés
  server.py        # WebSocket, lobby, échéances
  storage.py       # JSON atomique (users, games, archive)
  client/          # app Textual : app.py, screens.py, connection.py, config.py, logic.py
  cli.py           # cadav play | cadav serve
tests/
```
La logique de jeu reste pure (sans réseau ni disque), donc testable seule.

## 14. Jalons
1. `protocol.py` + `game.py` + tests (ordre, tours sautés, extraction d'amorce, projection, échéances). **Fait (53 tests).**
2. `storage.py` + `server.py`, testés avec un client WebSocket de script. **Fait (84 tests au total).**
3. Client Textual : lobby, création, salle d'attente. **Fait (130 tests au total).**
4. Écran de partie et reprise à la connexion.
5. Écran final, export, packaging `pipx`. **Fait (193 tests au total).**
6. Déploiement sur VPS (WSS) et essais en conditions réelles. **Préparé, non déployé** : aucun hébergement choisi à ce jour (voir §27).

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
- Lancement du serveur : `cadav serve --port 8765 --data-dir data` (options `--cert` et `--key` pour TLS), équivalent à `python -m cadav.server`.
- Dépendance ajoutée : `websockets` (prévue au §3).

## 18. Décisions d'implémentation (jalon 3)
- Le client est un paquet `cadav/client/` : `logic.py` (analyse du formulaire et textes, sans Textual ni réseau, testé seul), `config.py`, `connection.py` (WebSocket), `screens.py` et `app.py`. Lancement : `cadav play [--url ws://…] [--config fichier]`, équivalent à `python -m cadav.client`.
- Configuration locale : `~/.config/cadav/config.json` (ou `$XDG_CONFIG_HOME`, ou `$CADAV_CONFIG`), contenant `pseudo`, `secret` (64 caractères hexadécimaux) et `url` ; écrite de façon atomique avec les droits `0600`. URL par défaut : `ws://localhost:8765`.
- Premier lancement : écran de connexion (pseudo + serveur) ; le secret est généré à ce moment et n'est enregistré qu'une fois l'inscription acceptée. Un secret refusé par le serveur ramène à l'écran de connexion ; saisir le même pseudo réutilise le secret stocké, un autre pseudo crée un nouveau compte.
- Reconnexion automatique (1, 2, 4 puis 8 s) avec ré-authentification ; pas de reconnexion si la connexion a été remplacée par un autre terminal (code 4000) ou si le client est trop ancien (code 4001).
- Le client ne garde que `games` (les projections reçues) et `lobby` ; chaque message serveur remplace la projection concernée, et l'écran affiché se met à jour.
- Durée d'un tour : « Rapide » (2 min), « Tranquille » (24 h) ou saisie libre (`90s`, `10min`, `36h`, `2j` ; un nombre seul = minutes), entre 30 s et 72 h.
- Salle d'attente : code, réglages, joueurs en direct ; « Lancer » réservé à l'hôte et grisé sous 3 joueurs ; « Retour » quitte l'écran sans quitter la partie, « Quitter la partie » envoie `leave_game`.
- Une partie en cours s'affiche dans « Mes parties » (★ et « à toi ! » quand c'est le tour du joueur) ; son écran de jeu n'existe pas encore : un message le dit (jalon 4).
- Dépendance ajoutée : `textual` (prévue au §3).

## 19. Habillage et raccourcis (révision 6)
- Thème Textual `cadav` et feuille de style commune dans `cadav/client/theme.py` (palette Solarized dark : fond `#002b36`, surfaces `#073642`, texte `#839496`, bleu, cyan, magenta, vert, jaune et rouge canoniques ; pastilles `chip()`) ; styles propres à chaque écran dans la classe de l'écran (`CSS`, pas `DEFAULT_CSS`, qui serait écrasé par la feuille commune).
- Barre du haut (`TopBar`) sur chaque écran sauf la connexion ; pied de page Textual sans palette de commandes.
- Lobby : deux panneaux (« Mes parties » avec pastilles `À TOI`, `ATTENTE`, `EN COURS`, `TERMINÉE` ; « Parties publiques ») et un panneau « Rejoindre avec un code ». Raccourcis : `Ctrl+N` nouvelle partie, `Ctrl+K` saisir un code, `Entrée` ouvrir ou rejoindre la ligne choisie, `Ctrl+Q` quitter. Au retour d'un autre écran, le focus revient sur la liste pour que les raccourcis fonctionnent.
- Création : deux panneaux (« Partie », « Écriture »). `Ctrl+S` crée, `Échap` annule.
- Salle d'attente : code, joueurs (♛ = hôte), réglages, prochaine étape. `Ctrl+L` lance (hôte, 3 joueurs minimum), `Ctrl+O` quitte la partie, `Échap` revient au lobby.
- Les captures du README se régénèrent avec `scripts/screenshots.py` (serveur jetable + pilote de test Textual + `rsvg-convert`).

## 20. Navigation clavier, installation (révision 16)
- `cadav/client/widgets.py` : `NavInput` (champ à deux modes), `NavSelect` (choix : seuls `Entrée` et `Espace` l'ouvrent, `↑` `↓` ne l'ouvrent plus) et `NavOptionList` (liste qui passe le focus à l'élément voisin à ses extrémités, `Espace` comme `Entrée`). Les touches de navigation globales (`↑` `←` précédent, `↓` `→` suivant, `Tab`) sont des liaisons de l'application ; un menu ouvert ou un champ en cours de modification les reçoit en premier.
- Hors modification, `NavInput` ne consomme ni les flèches ni `Espace` (voir §21 pour la saisie directe). En modification, `↑` et `↓` sont sans effet, `←` `→` déplacent le curseur, un clic entre dans le champ, et perdre le focus valide la saisie.
- `Entrée` dans un champ valide le champ puis fait passer le focus à l'élément suivant (le champ « code » du lobby rejoint en plus la partie) ; `Échap` annule sans bouger. Choisir une option dans un menu (`Entrée` ou `Espace`) fait de même ; refermer le menu avec `Échap`, ou taper une lettre sur un choix fermé, laisse le focus en place. Sur l'écran de connexion, on valide la connexion avec le bouton « Entrer ».
- Le pied de page affiche les touches du mode courant (`Entrée Modifier`, ou `Entrée Valider` et `Échap Annuler`).
- Le paquet Python s'appelle `cadav/` (renommé depuis `cadavre/`). La commande est installable globalement : `uv tool install --editable .` (ou `pipx install --editable .`) place `cadav` dans `~/.local/bin`.
- Données du serveur par défaut : `$XDG_DATA_HOME/cadav` ou `~/.local/share/cadav` (et non plus `./data`), pour que `cadav serve` se comporte de la même façon quel que soit le dossier courant.

## 21. Palette, focus, saisie directe (révision 16)
- Palette par défaut : « galaxy », le thème de base de Posting repris sans modification (fichier `themes.py` de Posting) : primaire `#C45AFF`, secondaire `#a684e8`, avertissement `#FFD700`, erreur `#FF4500`, succès `#00FA9A`, accent `#FF69B4`, fond `#0F0F1F`, surface `#1E1E3F`, panneau `#2D2B55`, pied de page transparent, curseur de saisie `#C45AFF`. Pas de couleur de texte imposée : Textual la calcule, comme pour Posting (`auto 87 %`). Les nuances propres à cadav (gris du texte secondaire, ligne sélectionnée `#4b2c7a`, bordure atténuée, blanc d'édition) sont dérivées de ces couleurs. Option : `solarized-dark` (accent orange Solarized `#cb4b16`). Choix par `cadav play --theme …` ou par la clé `theme` de `config.json`.
- La feuille de style n'emploie que des variables de thème (`$accent`, `$cadav-focus`, `$cadav-editing`…) ; les styles Rich des écrans lisent la palette courante (`theme.colors`).
- Focus (repris du CSS de Posting, `posting.scss`) : panneaux `border: round $accent 40 %`, titre à droite en `$accent 50 %` (même couleur que le cadre) ; le panneau qui contient le focus passe à `round $accent 100 %` (toujours un cadre fin) avec un titre blanc gras. Champs et zones de texte : barre `outer` de la couleur du focus (primaire, la même que les menus, listes et boutons) sur le bord gauche quand ils ont le focus, pour les champs texte comme pour les champs numériques ; en modification, fond `$panel` et curseur plein (`input-cursor-background` = primaire, comme dans le thème galaxy). Ligne de liste, choix et bouton sélectionnés : « block cursor » = fond primaire, texte de la couleur du fond, gras ; ligne sélectionnée d'une liste sans focus : violet foncé `#4b2c7a`.
- Raccourcis : Lobby `Ctrl+N` (nouvelle partie), `Ctrl+K` (code) ; Création `Ctrl+S` ; Salle d'attente `Ctrl+L` (lancer), `Ctrl+O` (quitter la partie) ; partout `Ctrl+Q`, `Échap` pour revenir. Les lettres sont donc toujours du texte.
- Saisie directe : sur un `NavInput` qui n'est pas en modification, un caractère imprimable (sauf Espace) entre en modification, vide le champ et s'y inscrit ; `Échap` rétablit la valeur d'avant. Sur un `NavSelect` fermé, taper une lettre ou un chiffre (accumulés pendant 1 s) choisit la première option correspondante. Dans le menu ouvert, `Espace` valide comme `Entrée`.

## 22. Écran de partie et reprise (jalon 4, révision 10)
- `GameScreen` (dans `cadav/client/screens.py`) : panneau « Partie » (thème, ordre des joueurs, ▶ devant celui qui écrit), « Échéance du tour » (compte à rebours rafraîchi chaque seconde), « Amorce », « Ton texte » (zone multiligne, compteur de mots en direct, bouton Envoyer) et, une fois la partie terminée, « L'histoire » (chaque contribution attribuée, tours sautés listés). La copie et l'export restent au jalon 5.
- Ce n'est pas ton tour : le panneau « En cours » dit qui écrit et où l'on se trouve dans la file (« Tu es le prochain », « Ton tour viendra après N autre(s) joueur(s) », ou « Ton tour est passé » sans distinguer un tour joué d'un tour sauté, ce que le serveur ne révèle pas avant la fin).
- C'est ton tour : le focus va dans la zone de saisie. Le texte envoyé est celui de la zone sans espaces autour. Le compteur applique les limites de la partie (minimum, maximum, 2000 caractères) et le bouton est grisé hors limites ; `Ctrl+S` prévient au lieu d'envoyer.
- Brouillons : le texte non envoyé est conservé par partie tant que le client tourne (changer d'écran ou de partie ne le perd pas) ; il est effacé quand le serveur a pris le texte, et conservé si le serveur le refuse. Il n'est pas écrit sur disque.
- `Échap` quitte d'abord la zone de saisie (le focus passe sur Envoyer), puis revient au lobby. Quitter une partie en cours : `Ctrl+O`, à presser deux fois à moins de 5 secondes.
- Navigation entre parties : `Ctrl+T` va à la partie qui attend ton texte (puis la suivante, en boucle), `Ctrl+G` passe à ta partie suivante (en attente ou en cours). Disponibles depuis le lobby, la salle d'attente et l'écran de partie, pas depuis le formulaire de création.
- Bandeau discret (une ligne sous la barre du haut, 12 secondes) pour ce qui se passe dans les autres parties : « À toi dans « thème » », « le tour de X est passé », « est terminée », « est lancée ». Rien n'est affiché pour la partie que l'on regarde.
- Reprise : à la connexion, `my_games` redonne chaque partie avec sa projection (amorce comprise si c'est ton tour) ; le lobby marque `À TOI`, et `Ctrl+T` ouvre la partie. Rejoindre une partie qui démarre aussitôt (dernière place) ouvre directement l'écran de partie ; la salle d'attente se transforme en écran de partie au lancement.
- Raccourci de départ : `Ctrl+O` (et non `Ctrl+X`, que la zone de saisie utilise pour couper).

## 23. Écran final, export, paquet (jalon 5, révision 12)
- `FinalScreen` remplace le panneau d'histoire de l'écran de partie : il s'ouvre tout seul quand la partie se termine, ou depuis le lobby sur une partie `TERMINÉE` (le serveur les garde 7 jours, voir §10). Panneaux « Partie terminée » (thème, auteurs, tours sautés), « L'histoire » (défilement ; les flèches passent le focus au voisin quand on ne peut plus défiler) et « Garder l'histoire ».
- Export (`cadav/client/export.py`, pur et testé seul) : deux formats, Markdown (`# thème`, ligne en italique « Cadavre exquis écrit le 8 octobre 2026 par … », chaque contribution sous son auteur en gras, tours sautés) et texte brut (titre souligné, `— auteur —`). Nom de fichier : `cadav-<thème-sans-accents>-<AAAA-MM-JJ>.<md|txt>`, jamais d'écrasement (`-2`, `-3`…). Écriture atomique.
- Dossier d'export : champ modifiable, mémorisé dans la configuration (`export_dir`) après un enregistrement ; par défaut `~/Documents/cadav` si `~/Documents` existe, sinon `~/cadav`. Une erreur d'écriture est affichée sans fermer l'écran.
- Presse-papiers : texte brut de l'histoire. Le client appelle d'abord l'outil du système (`pbcopy`, `wl-copy`, `xclip`, `xsel` ou `clip`) puis demande aussi au terminal (OSC 52, utile à travers SSH) ; le message dit lequel a servi. Aucune dépendance ajoutée.
- Raccourcis : `Ctrl+S` enregistre, `Ctrl+Y` copie, `Échap` revient au lobby. `Ctrl+G` ignore les parties terminées.
- Paquet : nom `cadav`, version unique dans `cadav/__version__` (0.5.0), `cadav --version`, métadonnées (`readme`, URLs, classifiers). Installation : `pipx install git+https://github.com/charlescoiffier/cadav` (ou `uv tool install`). Pas de publication sur PyPI à ce stade, ni de licence choisie.
- CI : après les tests, un job construit la roue, l'installe dans un environnement vierge et lance `cadav --version`, `cadav serve --help` et `cadav play --help` ; la roue est gardée 7 jours comme artefact.

## 24. Fidélité à Posting (révision 16)
Relevé sur le dépôt de Posting (`posting.scss`, `app.py`, `widgets/select.py`, `themes.py`) et sur une capture de l'application :
- En-tête : `padding: 1 3` (trois lignes), nom en gras et version en atténué, `utilisateur@hôte` à droite en atténué. Chez cadav : `cadav <version> › <écran>` à gauche, `pseudo@serveur ● état` à droite.
- Pied de page : sans fond (transparent), `padding-left: 2`, touches en couleur d'accent et en gras, descriptions en texte normal ; pas de palette de commandes.
- Choix (`Select`) : `Entrée`, `Espace` ouvrent ; `↑` `↓` déplacent le focus d'un champ à l'autre ; dans le menu ouvert `Entrée` et `Espace` valident. C'est le comportement de `PostingSelect` / `PostingSelectOverlay`, déjà celui de cadav.
- Corps des écrans : marges latérales de 2 colonnes.

## 25. Mise en page des écrans (révision 16)
Structure commune : barre du haut, bandeau éventuel, **corps pleine hauteur** (`height: 1fr`, largeur 100 % avec 2 colonnes de marge), puis un **panneau du bas** (`.bottom`, mêmes marges que le corps) juste au-dessus du pied de page.
- Lobby : « Mes parties » et « Parties publiques » occupent toute la hauteur restante ; en bas, deux panneaux côte à côte, de la même largeur que les deux panneaux du dessus : « Rejoindre avec un code » à gauche (champ et bouton) et « Créer une partie » à droite (bouton, rappel de `Ctrl+N`).
- Nouvelle partie : « Partie » et « Écriture » ont la même hauteur (toute la hauteur) ; le panneau du bas contient le message d'erreur à gauche et les boutons Créer et Annuler alignés à droite.
- Salle d'attente : deux colonnes pleine hauteur, le dernier panneau de chaque colonne (« Joueurs », « Prochaine étape ») s'étire ; boutons alignés à droite dans le panneau du bas.
- Partie : colonne de gauche pleine hauteur (« Partie » s'étire, « Échéance du tour » en dessous), « Ton texte » prend toute la hauteur de la colonne de droite (la zone de saisie aussi) ; quand ce n'est pas ton tour, « En cours » prend cette hauteur ; Envoyer et Retour sont alignés à droite dans le panneau du bas (Envoyer n'est affiché que quand c'est ton tour).
- Écran final : « Partie terminée » et « L'histoire » pleine hauteur ; bords gauche et droit alignés sur ceux du panneau du bas « Garder l'histoire », dont les boutons sont à droite.
- Les tests vérifient ces géométries (régions des panneaux et des boutons).

## 26. Focus après un choix, champs numériques (révision 16)
- Après un choix dans un menu, `NavSelect` demande à l'écran où mettre le focus (`focus_after_choice`) ; sans réponse, c'est l'élément suivant. Formulaire de création : choisir « N derniers mots » met le focus sur le champ N (qui vient d'apparaître) ; choisir « Personnalisée… » le met sur le champ de durée.
- Les champs numériques (N, mots minimum, mots maximum) acceptent d'être vides (`valid_empty`) : ils ne sont plus marqués invalides au départ, ce qui supprimait leur barre de focus. Un champ réellement invalide reçoit une barre rouge (`$error`), comme dans Posting.

## 27. Déploiement (jalon 6, préparé, révision 16)
Aucun hébergement n'est choisi pour le moment ; tout ce qui ne dépend pas de l'hébergeur est prêt, et chaque pièce est testée.
- Serveur : option `--trust-proxy` (adresse du client lue dans `X-Forwarded-For`, pour la limitation par adresse), route `GET /health` en HTTP simple, arrêt propre sur `SIGTERM` / `SIGINT` (code 0), `--log-level`. Garde contre l'exposition par mégarde : écouter sur une adresse non locale exige `--cert` et `--key`, ou `--trust-proxy` (TLS terminé par un proxy), ou `--allow-insecure` (réseau de confiance) ; sinon le serveur refuse de démarrer.
- Fichiers dans `deploy/` : `Dockerfile` (utilisateur non privilégié, volume `/data`, `HEALTHCHECK`), `docker-compose.yml` (serveur + Caddy avec HTTPS automatique), `Caddyfile`, `Caddyfile.systemd`, `cadav.service` (systemd durci : utilisateur dynamique, système de fichiers en lecture seule sauf `StateDirectory`, mémoire limitée).
- Guide : `docs/deploiement.md` (jouer sans hébergeur : machine locale, réseau de confiance, réseau privé virtuel ; serveur public avec Docker, systemd ou TLS direct ; exploitation ; liste de contrôle de l'essai en conditions réelles).
- Tests (`tests/test_process.py`) : le serveur lancé comme un vrai processus joue une partie complète sur de vraies connexions, s'arrête proprement sur `SIGTERM`, redémarre sur les mêmes données et retrouve l'archive ; une partie en cours est restaurée (ordre, tour) ; `/health` ; refus d'une adresse publique sans chiffrement ; partie complète en `wss://` avec un certificat de test (et refus d'un client qui ne connaît pas le certificat). La CI construit l'image Docker, attend `/health` et vérifie l'arrêt propre.
- Reste à faire quand un hébergeur sera choisi : déployer, puis dérouler la liste de contrôle du guide sur des connexions réelles. Les clients utilisent `wss://` sans autre réglage ; le certificat est vérifié par le système.
