# Production checklist

Everything that has to be true before real families use 0FFDAYS, in order.
Tick it in a PR, not from memory. Deployment target: **k6-server**
(Hetzner, `178.156.233.148:2222`, user `jason`), sharing the box with
UtiliTrust and n8n.

Related: `infra/` (Containerfile, compose, nginx, deploy, backup, cron),
`.github/workflows/{ci,deploy}.yml`, `ops/ROSTER_SYNC.md`,
`ops/GUARDIAN_VERIFICATION.md`.

---

## 1. One-time server setup

- [ ] **DNS.** An `A` record for the app hostname (e.g. `app.0ffdays.com`)
      → `178.156.233.148`. If it is on Cloudflare, leave it **DNS only (grey
      cloud)** until the real-IP note in `infra/nginx.offdays.conf` is done.
      Otherwise every request looks like it came from Cloudflare and the guess
      throttle locks out whole regions at once.
- [ ] **Env file.** On the server:
      `mkdir -p ~/offdays/infra && cp infra/.env.prod.example ~/offdays/infra/.env.prod`
      (after the first rsync), then fill it in. See [§2](#2-environment-variables).
      `chmod 600` it.
- [ ] **First deploy** from a clean checkout: `./infra/deploy.sh k6-server`.
      It builds the image, starts `offdays_app_1` on `127.0.0.1:8810`, waits
      for `/api/live` to report the commit, and installs the cron block.
      `deploy.sh` needs `rsync` locally, and Git Bash on Windows has none. Run
      it from WSL, or just trigger the **Deploy** workflow by hand
      (Actions → Deploy → Run workflow), which is the normal path anyway.
- [ ] **nginx + TLS** (needs sudo, one time):
      ```
      sudo cp ~/offdays/infra/nginx.offdays.conf /etc/nginx/sites-available/offdays
      sudo ln -s /etc/nginx/sites-available/offdays /etc/nginx/sites-enabled/offdays
      sudo nginx -t && sudo systemctl reload nginx
      sudo certbot --nginx -d app.0ffdays.com
      ```
      certbot's existing timer on the box handles renewal.
- [ ] **Survives a reboot.** Rootless podman restarts `unless-stopped`
      containers through `podman-restart.service`, which is enabled
      system-wide, and `jason` has linger on (both checked Sept 2026, and
      UtiliTrust depends on the same thing). After the first deploy, run
      `sudo reboot` in a quiet window and confirm `offdays_app_1` comes back.
- [ ] **Log rotation.** `/etc/logrotate.d/offdays`:
      ```
      /home/jason/offdays-logs/*.log { weekly rotate 8 compress missingok notifempty copytruncate }
      ```
- [ ] **CI/CD secrets** on `mkallberg21/AthleteAI` (Settings → Secrets →
      Actions): `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`
      (`ssh-keyscan -p 2222 178.156.233.148`), `DEPLOY_HOST`, `DEPLOY_PORT`,
      `DEPLOY_USER`. Generate a **new** deploy key for this repo
      (`ssh-keygen -t ed25519 -C github-actions-deploy@offdays`) and add its
      public half to `~jason/.ssh/authorized_keys`. Don't reuse UtiliTrust's
      key.
- [ ] After the secrets are in: push to `main`, watch CI go green, and watch
      Deploy report `status: ok sha: <that commit>`.

## 2. Environment variables

`deploy.sh` **refuses to deploy** when a REQUIRED variable is blank and prints a
warning for the others. Graceful degradation is right in development. In
production it means a forgotten variable quietly ships a weaker product, so the
deploy is where it gets caught.

| Variable | Required | If unset | Notes |
|---|---|---|---|
| `OFFDAYS_SECRET` | **yes** | Unsubscribe links fall back to a public dev key, so anyone could forge one to switch off another person's mail. | `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`. Rotating it breaks existing unsubscribe links, nothing else. |
| `OFFDAYS_BASE_URL` | **yes** | Links in emails are relative/broken. | `https://app.0ffdays.com`, no trailing slash. |
| `OFFDAYS_STRICT_TEAM_SCOPE` | should be `1` | A coach with no team assignment sees the **whole program**. | Off only for upgrading old installs. |
| `OFFDAYS_DB_PATH` | set by compose | — | `/data/offdays.db` on the `offdays_data` volume. |
| `OFFDAYS_SMTP_HOST/PORT/USER/PASSWORD/FROM` | for email | Digests, guardian copies and parent reports are composed and shown in-app, never sent. | Any SMTP relay. Postmark or SendGrid free tier covers a pilot. The `FROM` domain needs SPF/DKIM or mail lands in spam. |
| `OFFDAYS_WEBHOOK_SECRET_{SENDGRID,POSTMARK,MAILGUN}` | for bounce handling | That provider's webhook endpoint is disabled (safe). | Set only the one you send through. |
| `OFFDAYS_SNS_TOPIC_ARNS` | only for SES | SES webhook disabled. | Leave blank unless sending through SES. |
| `OFFDAYS_VAPID_PUBLIC_KEY/PRIVATE_KEY/EMAIL` | for push | Notifications are in-app only, and a locked phone never buzzes. | `npx web-push generate-vapid-keys`, once. **Never rotate** after launch: every existing subscription dies. |
| `OFFDAYS_AUTH_MAX_FAILURES` | no (8) | — | Wrong codes before a lockout, per address and per code. |
| `OFFDAYS_AUTH_LOCKOUT_SECONDS` | no (30) | — | First lockout. Doubles per further failure. |
| `OFFDAYS_AUTH_LOCKOUT_MAX_SECONDS` | no (3600) | — | Cap. |
| `OFFDAYS_AUTH_FAILURE_WINDOW_SECONDS` | no (900) | — | Quiet period after which failures are forgotten. |
| `OFFDAYS_BUDGET_SCALE` | no (1.0) | — | Program-wide multiplier on training budgets. Capped at 1.0. |
| `PORT_APP` | no (8810) | — | Host port, `127.0.0.1` only. UtiliTrust owns 8801–8806. |

**Throttle and shared Wi-Fi.** 35 families on one club Wi-Fi share one public
address. Eight wrong codes from the whole building locks that address out for
30 s and then longer. At a sign-up night, raise `OFFDAYS_AUTH_MAX_FAILURES` to
~25 for the evening. The per-code counter still stops anyone hammering one
child's code.

## 3. Scheduled jobs

Installed by `deploy.sh` from `infra/crontab.offdays` (between
`# BEGIN offdays` / `# END offdays` markers; UtiliTrust's backup line in the
same crontab is left alone). All run inside the container with `podman exec`.

| Job | Schedule (UTC) | Does | Without it |
|---|---|---|---|
| `health_reap.py` | every 15 min | WAL checkpoint, closes abandoned sessions, disk alarm | WAL grows without limit and the review queue fills with dead sessions |
| `run_notifications.py` | hourly :05 | nudges, parent report, retention purges (wellness, clips), Monday coach digest, mail flush, push | **Nothing notifies anyone**, and expired child video is not deleted on time |
| `run_roster_sync.py` | every 6 h | auto-sync roster links | the auto-sync switch does nothing |
| `infra/backup.sh` | 03:47 daily | online backup + integrity check, gzip, 14-day retention, off-box copy | see §4 |
| `refresh_staples.py` | commented out | OCSP staples for SES/SNS | only needed with SES + strict revocation |

- [ ] `crontab -l` on the server shows the offdays block.
- [ ] After an hour: `tail ~/offdays-logs/*.log` shows each job has run.

## 4. Backups

- [ ] Nightly backup runs (`~/offdays-backups/offdays-*.db.gz`).
- [ ] **Off-box copy configured.** A backup on the same disk as the database
      is not a backup. Set `OFFSITE` in the crontab line for `backup.sh`
      (e.g. `OFFSITE=hbox:offdays`). Cheapest option on this stack: a
      **Hetzner Storage Box** (BX11, 1 TB, about €4/mo) as an rclone `sftp`
      remote. Backblaze B2 also works. One box can hold UtiliTrust's dumps too.
- [ ] **Restore drill, done once before go-live and dated here: ____**
      ```
      gunzip -c ~/offdays-backups/offdays-<stamp>.db.gz > /tmp/restore.db
      podman run --rm -v /tmp/restore.db:/data/offdays.db:Z -p 127.0.0.1:8899:8000 localhost/offdays:latest &
      curl -s http://127.0.0.1:8899/api/health    # status ok, schema_current true
      ```
      Real restore: stop the container, copy the file into the volume
      (`podman volume inspect offdays_data` for the path), start it.
- [ ] `BACKUP_HEARTBEAT_URL` set to an UptimeRobot heartbeat monitor so a
      missed night pages someone (§5).

## 5. Monitoring

UptimeRobot (already in use on another project, and the free tier is enough here):

- [ ] **HTTP(s) monitor** `https://app.0ffdays.com/api/live`, 5 min, keyword
      `"live":true`. Tells you the process and TLS are up.
- [ ] **Keyword monitor** `https://app.0ffdays.com/api/ready`, 5 min, alert
      when `"ready":true` is **absent**. Catches DB unreachable, stale schema,
      big WAL, low disk, stuck sessions, all from the existing health module.
- [ ] **Heartbeat monitor** for the nightly backup (`BACKUP_HEARTBEAT_URL`),
      interval 24 h + grace. Heartbeats are a paid UptimeRobot feature. On the
      free plan use healthchecks.io (free, 20 checks) for this one.
- [ ] Alert contact: your phone plus the developer.
- [ ] Certificate expiry: UptimeRobot's SSL monitoring on the HTTPS monitor.

### Do we need more horsepower?

No, not for this. k6-server has 4 vCPU, 7.6 GiB RAM (6.0 available) and
load 0.04 with UtiliTrust and n8n on it. 0FFDAYS runs pose inference **on the
athletes' phones**, and the server handles small JSON and SQLite writes. A
35-athlete pilot is a rounding error. The one thing to watch is disk: `/` is
**67% used (48 GB free)**, and most of that is UtiliTrust. Opt-in coach clips
are the only thing that grows fast here, and they are purged after 30 days. The
health endpoint degrades below 10% free, so UptimeRobot will say so.

**Prometheus + Grafana: not yet.** On a 7.6 GB box shared with a production app
that is ~500 MB+ of resident memory and another thing to patch, to chart numbers
`/api/health` already reports. Revisit when there are several programs, or move
it to the separate box below.

### A small separate ops box (recommended, not blocking)

Your instinct is right: keep monitoring **off** the thing it monitors, so an
outage on k6-server doesn't take the alerting down with it. Cheapest shape:

- **Hetzner CX22** (2 vCPU / 4 GB, about €4–5/mo) running **Uptime Kuma**
  (self-hosted UptimeRobot, one container) for every K6 project, and later
  Grafana + Prometheus/node_exporter scraping k6-server over a private network.
- Or skip the box: UptimeRobot/healthchecks.io are already off-box and free.

Recommendation for the pilot: UptimeRobot + healthchecks.io now (zero infra).
Add the ops box when a second paying program or a third K6 product lands.

### Static sites: Cloudflare Pages, not CloudFront

The prototype pages (`docs/` → `0ffdays.proto.k6-labs.com`, the Tennessee
page) are static HTML and belong on a CDN, not the app box. **Hetzner has no
CDN product.** For "CloudFront without AWS", use **Cloudflare Pages** (free,
unlimited bandwidth, custom domains, deploy-on-push from GitHub). GitHub Pages,
which is what those pages use today, is fine too. There's no reason to move
them unless you want everything under the Cloudflare account that already
fronts utilitrust.com. Do **not** put the *app* behind Cloudflare's proxy
without the real-IP change in the nginx config (§1).

## 6. Security and privacy gates

- [ ] `OFFDAYS_SECRET` set, `OFFDAYS_STRICT_TEAM_SCOPE=1` (deploy.sh checks).
- [ ] nginx sets `X-Forwarded-For $remote_addr` (overwrite, not append). Check:
      `grep X-Forwarded-For /etc/nginx/sites-enabled/offdays`.
- [ ] Guess throttle works through the proxy: 9 wrong codes at
      `POST /api/me/login` from one phone → HTTP 429 with `Retry-After`.
- [ ] Guardian verification decision recorded: see
      `ops/GUARDIAN_VERIFICATION.md`. Decision: ______ (date ____)
- [ ] Coach video consent **left off** for the pilot unless a guardian asks.
      Clips live unencrypted in SQLite (README "Known limitations" #1).
- [ ] Film study (third-party embeds) reviewed or disabled for this club.
- [ ] Nothing seeded: the production DB must not contain `seed_demo.py` users.
      (`deploy.sh` never seeds. Don't run the seeder against `/data`.)

## 7. Product gates (before families)

- [ ] Wall-ball calibration: ≥ 6 own-youth clips in realistic/poor light per
      drill through `/app/calibrate.html`, `calibration.verdict()` = `measured`
      (or retuned). Tracked in the pilot task list.
- [ ] Real phone end to end over HTTPS: an athlete signs in with a code, the
      camera opens, a wall-ball session counts and submits, and it appears on
      the coach dashboard. Test on **one iPhone (Safari) and one Android
      (Chrome)**.
- [ ] Offline: open capture once online, go to airplane mode, record, come
      back online, and check the session uploads from the queue.
- [ ] Roster imported by CSV (`ops/ROSTER_SYNC.md`), preview read by the coach
      before import.
- [ ] Guardian invites delivered (email if SMTP is set, otherwise printed
      codes handed out by the coach).
- [ ] Consent / wellness / coach-video screens walked through by one
      non-technical parent (scheduled right before go-live).
- [ ] Billing: pilot runs on the free/manual plan. `ManualGateway` records
      plans and charges nothing. No Stripe.

## 8. Go-live day

- [ ] Deploy the tagged commit and confirm `/api/health` → `status: ok`,
      `git_sha` matches.
- [ ] Fresh backup taken by hand (`~/offdays/infra/backup.sh`) and copied off.
- [ ] Raise `OFFDAYS_AUTH_MAX_FAILURES` for the sign-up session (§2) and put it
      back afterwards.
- [ ] Someone watching UptimeRobot and `~/offdays-logs/` for the first week.
