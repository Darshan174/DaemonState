# deploy/

Concrete reverse-proxy configs for self-hosted Context Engine deployments.

The API container binds to `127.0.0.1:8000` on the host by default (see
`docker-compose.yml`), so a TLS-terminating proxy on the same host is
required for any internet-facing deployment. These configs are drop-in
starting points — edit the domain, verify the cert path, reload.

## Which one should I use?

| You already run… | Use |
|---|---|
| Nothing | **Caddy** — auto-TLS via Let's Encrypt, zero cert management |
| nginx | `nginx/context-engine.conf` (cert via `certbot --nginx`) |
| Cloudflare in front | Either — set up proxy-mode DNS and origin certs |
| Tailscale / Cloudflare Access / WireGuard | Neither — bind the API to the tunnel interface and skip TLS |

When in doubt, use Caddy. It's a single binary with no cert ceremony
and the Caddyfile is shorter than the nginx equivalent.

## Files

- `caddy/Caddyfile` — Caddy config. Copy to `/etc/caddy/Caddyfile`.
- `nginx/context-engine.conf` — nginx server block. Copy to
  `/etc/nginx/sites-available/` and symlink into `sites-enabled/`.

Both include commented-out snippets for optional basic auth and IP
allow-listing, which are the two quickest ways to lock down a demo
deployment while you figure out a real auth story.

## Before you expose the API

1. **Bind postgres and redis to loopback.** The default
   `docker-compose.yml` already does this (`HOST_POSTGRES_BIND=127.0.0.1`,
   `HOST_REDIS_BIND=127.0.0.1`). Do not change unless you know what you
   are doing.
2. **Open only the ports the proxy needs.** On Ubuntu:
   ```bash
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```
3. **Verify the API is not directly reachable.** From a different host:
   ```bash
   curl -sS --max-time 5 http://your-vps-ip:8000/health
   # Expected: Connection refused (the API is bound to 127.0.0.1 only).
   ```
4. **Turn on the reverse proxy, verify HTTPS:**
   ```bash
   curl -sS https://your-domain.example.com/health
   # Expected: {"status":"ok",...}
   ```
5. **Run the smoke suite from the VPS** (works because smoke.sh talks
   to `http://localhost:8000` on loopback):
   ```bash
   bash scripts/smoke.sh
   ```

See `docs/self-hosting.md` for the full deployment story and
`docs/runbook.md` for the ops runbook (backup, upgrade, diagnostics).
