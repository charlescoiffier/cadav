# cadav : cadavre exquis TUI

Jeu de cadavre exquis textuel multijoueur en terminal (Python, Textual, WebSocket).

**Source de vérité : `cahier-des-charges.md`.** Lis-le en entier avant toute modification. Si une décision change en cours de route, mets à jour le cahier des charges dans la même session.

## Principes à respecter
- Le serveur central gère toutes les parties ; le client ne reçoit jamais l'état complet, seulement `view_for(game, pseudo)`.
- La logique de jeu (`game.py`) est pure : pas de réseau, pas de disque, pas d'horloge implicite (l'heure est injectée). Elle doit être testable seule.
- Pas de base de données : fichiers JSON avec écriture atomique (fichier temporaire puis `os.replace`).
- Protocole : modèles Pydantic dans un module partagé, avec un numéro de version.
- Pas de dépendance ajoutée sans raison : bibliothèque standard d'abord.

## Conventions
- Identifiants de code et commentaires en anglais ; textes affichés à l'utilisateur en français.
- Tests avec `pytest` + `pytest-asyncio`. Écrire les tests de la logique pure avant le serveur.
- Un jalon à la fois, dans l'ordre du §14 du cahier des charges ; s'arrêter à la fin de chaque jalon pour que l'utilisateur valide.

## Par où commencer
Jalon 1 : `protocol.py`, `game.py` et leurs tests.
