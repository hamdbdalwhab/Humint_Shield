/**
 * HUMINT Shield — Cloudflare Worker front door.
 *
 * Serves the compiled React dashboard from static assets and proxies the
 * Python/FastAPI backend (running behind a tunnel) for:
 *   /api/*     — REST API
 *   /s/*       — SMS short links (click tracking + redirect)
 *   /healthz   — liveness
 *   /metrics   — Prometheus scrape
 *
 * Everything else falls back to the SPA shell so React Router deep links
 * (/sms-lure/:uuid, /training/:uuid, /qr/...) work on a hard refresh.
 */

/**
 * Public origin of the FastAPI backend.
 *
 * Set this in the Cloudflare dashboard / Wrangler as a secret or variable:
 *   wrangler secret put BACKEND_ORIGIN
 * Example: https://your-backend.example.com
 *
 * Never commit a live tunnel URL here: quick tunnels are temporary and the
 * Worker must be redeployed whenever the backend origin changes.
 */
const BACKEND_ORIGIN = '';

const PROXIED_PREFIXES = ['/api/', '/s/'];
const PROXIED_PATHS = new Set(['/healthz', '/metrics']);

export default {
  /**
   * @param {Request} request
   * @param {{ASSETS: {fetch: (request: Request) => Promise<Response>}, BACKEND_ORIGIN?: string}} env
   * @returns {Promise<Response>}
   */
  async fetch(request, env) {
    const url = new URL(request.url);
    const shouldProxy =
      PROXIED_PATHS.has(url.pathname) ||
      PROXIED_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));

    if (shouldProxy) {
      const backendOrigin = (env.BACKEND_ORIGIN || BACKEND_ORIGIN || '').trim();
      if (!backendOrigin) {
        return new Response(
          JSON.stringify({
            detail:
              'BACKEND_ORIGIN is not configured for this Worker. Set it to the public FastAPI origin.',
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          },
        );
      }
      const target = new URL(`${url.pathname}${url.search}`, backendOrigin);
      const headers = new Headers(request.headers);
      // The API builds absolute links (tracking, redirects) from these headers.
      headers.set('X-Forwarded-Host', url.host);
      headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''));
      headers.set('X-Real-IP', request.headers.get('CF-Connecting-IP') || '');

      const proxied = new Request(target.toString(), {
        method: request.method,
        headers,
        body:
          request.method === 'GET' || request.method === 'HEAD'
            ? undefined
            : request.body,
        redirect: 'manual',
      });

      const response = await fetch(proxied);
      const out = new Headers(response.headers);
      out.set('Access-Control-Allow-Origin', url.origin);
      out.set('Vary', 'Origin');
      return new Response(response.body, {
        status: response.status,
        headers: out,
      });
    }

    return env.ASSETS.fetch(request);
  },
};
