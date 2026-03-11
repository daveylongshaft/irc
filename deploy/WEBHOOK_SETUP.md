# GitHub Webhook Setup for csc-csc-agent

## 1. Set the webhook secret in `.env`

Add the following line to `/opt/csc/.env` (create if missing):

```
GITHUB_WEBHOOK_SECRET=ebef3e7e93626be51b0a1e73c9f6517271c0dafdcb79be68852a39df8814514a
```

> **Keep this secret.** Rotate it by generating a new value with
> `python3 -c "import secrets; print(secrets.token_hex(32))"` and updating both
> `.env` and the GitHub App settings.

## 2. Install and enable the webhook listener service

```bash
# Install the package (if not already done)
pip install -e /opt/csc/packages/csc-service

# Copy/render the service template
cp /opt/csc/deploy/services/csc-webhook.service.template /etc/systemd/system/csc-webhook.service

# Edit placeholders in the unit file
sed -i "s|{USER}|$(whoami)|g;s|{GROUP}|$(id -gn)|g;s|{INSTALL_DIR}|/opt/csc|g;s|{PYTHON}|$(which python3)|g" \
    /etc/systemd/system/csc-webhook.service

systemctl daemon-reload
systemctl enable --now csc-webhook
systemctl status csc-webhook
```

Alternatively, start it directly (for testing):

```bash
GITHUB_WEBHOOK_SECRET=<secret> CSC_ROOT=/opt/csc python3 -m csc_service.infra.webhook_listener
```

## 3. Enable Apache reverse proxy

```bash
a2enmod proxy proxy_http
ln -sf /opt/csc/deploy/apache-webhook.conf /etc/apache2/conf-enabled/apache-webhook.conf
apachectl configtest
systemctl reload apache2
```

## 4. Update the GitHub App settings

In the GitHub App `csc-csc-agent` (ID: 3060746) → **Settings** → **General**:

| Field           | Value |
|-----------------|-------|
| Webhook Active  | ✓ |
| Payload URL     | `https://facingaddictionwithhope.com/csc-webhook` |
| Content type    | `application/json` |
| Secret          | `ebef3e7e93626be51b0a1e73c9f6517271c0dafdcb79be68852a39df8814514a` |
| Events          | **Pull requests** |

## 5. Validation

1. In GitHub App settings → **Advanced** → **Recent Deliveries**, click **Redeliver** on the
   most recent delivery (or trigger a new one).
2. Check the listener log:
   ```bash
   journalctl -u csc-webhook -f
   # or if running directly:
   # watch the stdout
   ```
3. Verify `bin/pr-review-agent.sh` is triggered for `opened`/`synchronize` actions.

## Architecture

```
GitHub  →  HTTPS POST /csc-webhook  →  Apache  →  http://127.0.0.1:5000/webhook
                                                    (csc-webhook systemd service)
                                                           ↓
                                                    bin/pr-review-agent.sh
```
