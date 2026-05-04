# Aulamat Server Deployment

This Ansible setup deploys the Docker-based summary server to `kolenovo` as user `kasper`.

Create local deployment variables:

```bash
cp deploy/vars.example.yml deploy/vars.yml
vim deploy/vars.yml
```

`deploy/vars.yml` is ignored by git. Put your MitID username and OpenAI API key there. By default, the playbook copies your local `.aula_tokens.json` to the server so the summary server can start with the existing Aula session.

Run from the repository root:

```bash
ansible-playbook -i deploy/inventory.ini deploy/playbook.yml --extra-vars @deploy/vars.yml
```

Add `-K` if `kasper` needs a sudo password on `kolenovo`.

The token cache is copied to `/opt/aula/data/.aula_tokens.json` with mode `0600`. If you want to skip token transfer and do the first login on the server instead, set `copy_local_token: false` in `deploy/vars.yml`.

The server layout is:

```text
/opt/aula/
  compose.yml
  .env
  data/
    .aula_tokens.json
    .aula_scan_state.json
    .aula_raw/
```

The summary server is bound to `0.0.0.0:8767` on `kolenovo`, so it should be reachable on your LAN at:

```text
http://kolenovo:8767/
```

Only run it this way on a trusted network or behind an access layer, since the page can show Aula message summaries.

If you do not copy a token cache, run the first login on the server:

```bash
ssh kasper@kolenovo
cd /opt/aula
docker compose run --rm aula-summary aula-project login
docker compose up -d
```

Do not commit real `.env` files, token caches, scan state, raw captures, or vault passwords.

## Notifications

Server-side notifications run as an optional second Compose service. Configure an Apprise URL in `deploy/vars.yml`, then enable the service:

```yaml
aula_notify_url: "ntfy://ntfy.sh/YOUR_PRIVATE_TOPIC"
aula_notify_enabled: true
aula_notify_interval_minutes: 20
aula_notify_thread_limit: 20
aula_notify_min_priority: medium
```

Pushover is also a good fit:

```yaml
aula_notify_url: "pover://USER_KEY@APP_TOKEN"
```

After changing notification settings, rerun the playbook. The notifier uses the same `/opt/aula/data/.aula_tokens.json` and `/opt/aula/data/.aula_scan_state.json` files as the summary server.
