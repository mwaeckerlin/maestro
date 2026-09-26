# Traefik routes /spark-test/maestro to the harness and strips the prefix, the
# way the Swarm deployment routes /<hostname>/maestro to Maestro.
FROM traefik
COPY traefik.yml /etc/traefik/traefik.yml
COPY dynamic.yml /etc/traefik/dynamic.yml
