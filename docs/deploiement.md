# Héberger un serveur cadav

Le serveur est un seul processus (`cadav serve`) qui garde ses données dans un dossier. Rien de plus : pas de base de
données, pas de service externe. Cette page décrit comment le faire tourner, de « chez soi » jusqu'à un serveur public.

## Sans hébergeur

Le jeu se joue très bien sans serveur public.

**Sur sa machine** : `cadav serve` écoute sur `127.0.0.1:8765`, uniquement accessible depuis l'ordinateur. Chaque joueur
local lance `cadav play --config /tmp/joueur1.json` (un fichier de configuration par joueur).

**Sur un réseau de confiance** (maison, bureau) : écouter sur toutes les interfaces, sans chiffrement.

```bash
cadav serve --host 0.0.0.0 --allow-insecure
```

Les autres se connectent avec `cadav play --url ws://adresse-de-la-machine:8765`. Les pseudos et les secrets passent en clair
sur le réseau : à réserver à un réseau où l'on a confiance. Sans `--allow-insecure`, le serveur refuse d'écouter sur autre
chose que la boucle locale, pour qu'on ne l'expose pas par mégarde.

**Entre amis à distance, sans serveur public** : un réseau privé virtuel (par exemple Tailscale ou WireGuard) donne à chacun
une adresse privée vers la machine qui héberge ; on utilise alors la commande du paragraphe précédent avec cette adresse.

## Sur un serveur public (VPS, machine dédiée, Raspberry Pi derrière une box)

Il faut : une machine allumée en permanence, un nom de domaine qui pointe vers elle, les ports 80 et 443 ouverts. Le serveur
cadav lui-même ne gère pas la sortie sur Internet : un **proxy inverse** (Caddy ici) termine le TLS, obtient et renouvelle
le certificat Let's Encrypt, et transmet les WebSocket au serveur sur le réseau interne. L'option `--trust-proxy` dit au
serveur de lire l'adresse réelle des joueurs dans `X-Forwarded-For` pour limiter les tentatives de connexion par joueur et non
pour tout le monde à la fois.

### Avec Docker

```bash
git clone https://github.com/charlescoiffier/cadav && cd cadav
export CADAV_DOMAIN=cadav.exemple.org
docker compose -f deploy/docker-compose.yml up -d --build
```

Les comptes et les parties sont dans le volume `cadav-data`. Mise à jour : `git pull` puis la même commande `up -d --build`.

### Avec systemd

```bash
sudo python3 -m venv /opt/cadav
sudo /opt/cadav/bin/pip install git+https://github.com/charlescoiffier/cadav
sudo cp deploy/cadav.service /etc/systemd/system/
sudo systemctl enable --now cadav
```

Puis installer Caddy et y copier `deploy/Caddyfile.systemd` (en remplaçant le nom de domaine). Les données sont dans
`/var/lib/cadav`. Mise à jour : `sudo /opt/cadav/bin/pip install -U git+https://github.com/charlescoiffier/cadav` puis
`sudo systemctl restart cadav`.

### Sans proxy

Le serveur sait aussi parler TLS tout seul : `cadav serve --host 0.0.0.0 --cert fullchain.pem --key privkey.pem`
(avec un certificat obtenu par ailleurs, par exemple avec `certbot`). Le renouvellement du certificat est alors à votre charge.

### Se connecter

```bash
cadav play --url wss://cadav.exemple.org
```

## Exploitation

- **Santé** : `GET /health` répond `200 ok` en HTTP simple (supervision, `HEALTHCHECK` de Docker).
- **Arrêt** : `SIGTERM` ou `SIGINT` arrête proprement le serveur (code de sortie 0). Chaque changement étant écrit sur disque
  avant d'être oublié, un arrêt brutal ne perd pas de partie ; au redémarrage, les échéances sont reprogrammées et celles
  qui sont passées s'appliquent aussitôt.
- **Journaux** : sur la sortie d'erreur (`journalctl -u cadav`, `docker logs`) ; `--log-level DEBUG` pour plus de détails.
- **Sauvegarde** : copier le dossier de données (`users.json`, `games/`, `archive/`). Les écritures sont atomiques : une copie
  à chaud est cohérente fichier par fichier.
- **Limites intégrées** : 5 parties actives par pseudo, 10 créations de partie par heure et par pseudo, 1000 parties
  simultanées, 20 inscriptions ou échecs de connexion par tranche de 10 minutes et par adresse, messages de 64 Ko au plus.
- **Mises à jour du protocole** : un client trop ancien est refusé avec un message clair (`unsupported_version`).

## Essai en conditions réelles : liste de contrôle

Les tests automatiques couvrent déjà un serveur lancé comme un vrai processus (partie complète sur de vraies connexions,
arrêt par `SIGTERM`, redémarrage avec les mêmes données, TLS avec un certificat de test). Avec un serveur réellement hébergé,
il reste à vérifier à la main :

1. `curl https://cadav.exemple.org/health` répond `ok` avec un certificat valide.
2. `cadav play --url wss://cadav.exemple.org` : inscription, création d'une partie privée, un second joueur la rejoint par code.
3. Une partie à trois sur des connexions différentes (réseau mobile compris), avec un tour sauté volontairement
   (échéance de 30 secondes).
4. Couper la connexion d'un joueur en pleine partie : il se reconnecte tout seul et retrouve son tour.
5. `docker compose restart cadav` (ou `systemctl restart cadav`) en pleine partie : les parties et les échéances reviennent.
6. Plusieurs inscriptions depuis des adresses différentes : la limitation par adresse ne bloque pas tout le monde
   (c'est le rôle de `--trust-proxy`).
