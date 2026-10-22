# Edge Nginx (optional)

`humint-shield.conf` is an **optional** TLS-terminating reverse proxy for
production deployments that want certificates, HSTS and a single public hostname
in front of the stack.

The default `docker-compose.yml` already ships an nginx container
(`frontend`, see `frontend/nginx.conf`) that serves the SPA and proxies
`/api/` and `/training/` to the backend. You only need this edge proxy when:

- TLS certificates are terminated in your own infrastructure, or
- you run the compose stack on an internal network behind a corporate LB, or
- you need HSTS / custom security headers at the edge.

## Usage

1. Replace `humint.example.com` with your hostname in `humint-shield.conf`.
2. Mount the file and certificates, e.g.:

   ```yaml
   # docker-compose.override.yml
   services:
     edge:
       image: nginx:1.27-alpine
       ports: ['80:80', '443:443']
       volumes:
         - ./nginx/humint-shield.conf:/etc/nginx/conf.d/default.conf:ro
         - ./certbot/conf:/etc/letsencrypt:ro
         - ./certbot/www:/var/www/certbot:ro
       depends_on: [frontend]
       networks: [humint]
   ```

3. `docker compose up -d`, then obtain certificates with certbot (webroot mode
   pointing at `/var/www/certbot`).

## Reminder

Tracking links are rewritten to `{BASE_URL}/api/v1/track/click/{uuid}` where
`BASE_URL` is the backend's own public address. Set `BASE_URL` in `.env` to the
**externally reachable** HTTPS URL, otherwise links inside delivered emails will
point at an address recipients cannot open.
