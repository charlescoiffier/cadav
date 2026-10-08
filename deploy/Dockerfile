# Image du serveur cadav. Construire depuis la racine du dépôt :
#   docker build -f deploy/Dockerfile -t cadav .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /src
COPY pyproject.toml README.md ./
COPY cadav ./cadav
RUN pip install . && rm -rf /src

# Les données (comptes, parties, archives) vivent dans un volume : elles survivent aux mises à jour.
RUN useradd --system --uid 10001 --home-dir /data cadav && mkdir -p /data && chown cadav /data
USER cadav
VOLUME /data
EXPOSE 8765

# Le TLS est géré par un proxy devant (voir docker-compose.yml) : le serveur parle en clair sur le réseau interne.
CMD ["cadav", "serve", "--host", "0.0.0.0", "--port", "8765", "--data-dir", "/data", "--trust-proxy"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)"
