# Production checklist

Everything that has to be true before real families use 0FFDAYS, in order.
Tick it in a PR, not from memory. Deployment target: **k6-server**
(Hetzner, `178.156.233.148:2222`, user `jason`), sharing the box with
UtiliTrust and n8n.

**The decisions behind this list (email provider, monitoring, DNS, hosting)
are in `ops/DECISIONS.md`. Read it before proposing a different tool.**

Related: `infra/` (Containerfile, compose, nginx, deploy, backup, cron),
`.github/workflows/{ci,deploy}.yml`, `ops/ROSTER_SYNC.md`,
`ops/GUARDIAN_VERIFICATION.md`.

Live since 2026-09-28 at `https://app.0ffdays.com`.

---

## 1. One-time server setup

- [x] **DNS.** `app.0ffdays.com` A → `178.156.233.148` in Cloudflare, **DNS
      only (grey cloud)**. It has to stay grey until the real-IP note in
      `infra/nginx.offdays.conf` is done, or every request looks like it came
      from Cloudflare and the guess throttle locks out whole regions at once.
- [x] **Env file.** `~/offdays/infra/.env.prod` on the server, mode 600,
      holding a generated `OFFDAYS_SECRET`, the base URL and strict team scope.
      SMTP and VAPID are still blank (§2).
- [x] **First deploy.** Commit `cb9d352` went out through Actions → Deploy.
      `deploy.sh` needs `rsync` locally and Git Bash on Windows has none, so
      deploy from CI (the normal path) or WSL.
- [x] **nginx + TLS.** `/etc/nginx/sites-enabled/offdays` with a Let's
      Encrypt certificate (expires 2026-12-27, renewed by the box's certbot
      timer). http redirects to https.
- [ ] **Survives a reboot.** Rootless podman restarts `unless-stopped`
      containers through `podman-restart.service` (enabled system-wide), and
      `jason` has linger on. UtiliTrust depends on the same thing. Run
      `sudo reboot` in a quiet window and confirm `offdays_app_1` comes back.
- [ ] **Log rotation.** `/etc/logrotate.d/offdays`:
      ```
      /home/jason/offdays-logs/*.log { weekly rotate 8 compress missingok notifempty copytruncate }
      ```
- [x] **CI/CD secrets** `DEPLOY_SSH_KEY` (new key,
      `github-actions-deploy@offdays`, only for this repo), `DEPLOY_KNOWN_HOSTS`,
      `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER` on `mkallberg21/AthleteAI`.
- [x] CI green and Deploy reporting `status: ok sha: <commit>`.

## 2. Environment variables

`deploy.sh` **refuses to deploy** when a REQUIRED variable is blank and prints
a warning for the others. It reads the file with grep and never sources it,
because this is a podman env-file and values are literal. Graceful degradation
is right in development. In production a forgotten variable quietly ships a
weaker product, so the deploy is where it gets caught.

| Variable | Required | If unset | Notes |
|---|---|---|---|
| `OFFDAYS_SECRET` | **yes** | Unsubscribe links fall back to a public dev key, so anyone could forge one to switch off another person's mail. | `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`. Rotating it breaks existing unsubscribe links, nothing else. |
| `OFFDAYS_BASE_URL` | **yes** | Links in emails are relative/broken. | `https://app.0ffdays.com`, no trailing slash. |
| `OFFDAYS_STRICT_TEAM_SCOPE` | should be `1` | A coach with no team assignment sees the **whole program**. | Off only for upgrading old installs. |
| `OFFDAYS_DB_PATH` | set by compose | — | `/data/offdays.db` on the `offdays_data` volume. |
| `OFFDAYS_SMTP_HOST/PORT/USER/PASSWORD/FROM` | for email | Digests, guardian copies and parent reports are composed and shown in-app, never sent. | **Resend** (`ops/DECISIONS.md`): host `smtp.resend.com`, port 587, user `resend`, password = API key, From on `mail.0ffdays.com`. |
| `OFFDAYS_WEBHOOK_SECRET_{SENDGRID,POSTMARK,MAILGUN}` | no | That provider's endpoint is disabled (safe). | Leave blank. There's no Resend verifier yet, and bounce webhooks are off for the pilot. |
| `OFFDAYS_SNS_TOPIC_ARNS` | **no, leave blank** | SES webhook disabled. | Not using SES/SNS (`ops/DECISIONS.md`). |
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
| `refresh_staples.py` | **off** | OCSP staples for SES/SNS | not needed: no SES (`ops/DECISIONS.md`) |

- [x] `crontab -l` on the server shows the offdays block (5 jobs).
- [ ] After a day: `tail ~/offdays-logs/*.log` shows each job has run.

## 4. Backups

- [x] Nightly backup runs (`~/offdays-backups/offdays-*.db.gz`). Verified by
      hand 2026-09-28.
- [ ] **Off-box copy configured.** A backup on the same disk as the database
      is not a backup. Set `OFFSITE` in the crontab line for `backup.sh`
      (e.g. `OFFSITE=hbox:offdays`). Options: a **Hetzner Storage Box**
      (BX11, 1 TB, about €4/mo) as an rclone `sftp` remote, or the planned
      utility server over the tailnet. One target can hold UtiliTrust's dumps
      too.
- [ ] **Restore drill, done once before go-live and dated here: ____**
      ```
      gunzip -c ~/offdays-backups/offdays-<stamp>.db.gz > /tmp/restore.db
      podman run --rm -v /tmp/restore.db:/data/offdays.db:Z -p 127.0.0.1:8899:8000 localhost/offdays:latest &
      curl -s http://127.0.0.1:8899/api/health    # status ok, schema_current true
      ```
      Real restore: stop the container, copy the file into the volume
      (`podman volume inspect offdays_data` for the path), start it.
- [ ] `BACKUP_HEARTBEAT_URL` set to a Kuma Push monitor or a healthchecks.io
      check, so a missed night alerts Discord (§5).

## 5. Monitoring

**Uptime Kuma posting to the team Discord channel.** Not UptimeRobot, whose
free plan alerts one recipient only. Reasons and the full setup are in
`ops/DECISIONS.md`.

- [x] Kuma running (Podman on Matt's workstation, localhost:3001), with the
      Discord webhook tested and set as the default notification.
- [x] **0FFDAYS ready**: `https://app.0ffdays.com/api/ready`, keyword
      `"ready":true`, 60 s, 2 retries. Catches DB unreachable, stale schema,
      big WAL, low disk and stuck sessions.
- [x] **0FFDAYS live**: `https://app.0ffdays.com/api/live`, keyword
      `"live":true`, 60 s. Process and TLS up.
- [x] **UtiliTrust app**: `https://app.utilitrust.com`, 60 s.
- [x] Certificate-expiry notification on the HTTPS monitors.
- [ ] Kuma survives a workstation reboot (linger + `podman-restart.service`
      are enabled, not yet tested).
- [ ] **Dead-man switch** on healthchecks.io, posting to the same Discord
      webhook, so that "the workstation is off" also alerts someone.
- [ ] Backup heartbeat (§4).
- [ ] SMS: later, through a paid Kuma provider (Twilio or ClickSend).
- [ ] Move Kuma to the utility server once it exists (`ops/DECISIONS.md`).

### Do we need more horsepower?

No, not for this. k6-server has 4 vCPU, 7.6 GiB RAM (6.0 available) and
load 0.04 with UtiliTrust and n8n on it. 0FFDAYS runs pose inference **on the
athletes' phones**, and the server handles small JSON and SQLite writes. A
35-athlete pilot is a rounding error. The one thing to watch is disk: `/` is
**67% used (48 GB free)**, and most of that is UtiliTrust. Opt-in coach clips
are the only thing that grows fast, and they are purged after 30 days.
`/api/ready` goes not-ready below 10% free, so Kuma will alert.

**Prometheus + Grafana: not yet.** On a 7.6 GB box shared with a production
app that is ~500 MB+ of resident memory and another thing to patch, to chart
numbers `/api/health` already reports. It goes on the utility server when
there are several programs.

### Static sites: Cloudflare Pages, not CloudFront

The prototype pages (`docs/` → `0ffdays.proto.k6-labs.com`, the Tennessee
page) are static HTML and belong on a CDN, not the app box. **Hetzner has no
CDN product.** For "CloudFront without AWS", use **Cloudflare Pages** (free,
unlimited bandwidth, custom domains, deploy-on-push from GitHub). GitHub
Pages, which those pages use today, is fine too. Do **not** put the *app*
behind Cloudflare's proxy without the real-IP change in the nginx config (§1).

## 6. Security and privacy gates

- [x] `OFFDAYS_SECRET` set, `OFFDAYS_STRICT_TEAM_SCOPE=1` (deploy.sh checks).
- [x] nginx sets `X-Forwarded-For $remote_addr` (overwrite, not append).
- [x] Guess throttle works through the proxy: 10 wrong codes with a forged,
      rotating `X-Forwarded-For` → 401 ×8, then 429 with `Retry-After`
      (2026-09-28).
- [ ] Guardian verification decision recorded: see
      `ops/GUARDIAN_VERIFICATION.md`. Decision: ______ (date ____)
- [ ] Coach video consent **left off** for the pilot unless a guardian asks.
      Clips live unencrypted in SQLite (README "Known limitations" #1).
- [ ] Film study (third-party embeds) reviewed or disabled for this club.
- [ ] Nothing seeded: the production DB must not contain `seed_demo.py` users.
      (`deploy.sh` never seeds. Don't run the seeder against `/data`.)

## 7. Product gates (before families)

- [ ] **Email sending** set up through Resend on `mail.0ffdays.com`, with
      DKIM, SPF and DMARC (`ops/DECISIONS.md`). Guardian invites are queued
      with a sign-up link on roster import (`ops/FAMILY_ONBOARDING.md`), but
      until SMTP is set they only reach the log, and printed codes are the
      real path.
- [ ] Wall-ball calibration: ≥ 6 own-youth clips in realistic/poor light per
      drill through `/app/calibrate.html`, `calibration.verdict()` = `measured`
      (or retuned).
- [ ] Headless mobile check (Playwright with iPhone/Pixel emulation, a fake
      camera and offline). It needs a clearly marked test org in production,
      deleted afterwards, and a wall-ball clip.
- [ ] Real phone end to end over HTTPS: an athlete signs in with a code, the
      camera opens, a wall-ball session counts and submits, and it appears on
      the coach dashboard. Test on **one real iPhone (Safari)**, since the
      headless run can't prove iOS camera or permission behaviour, and one
      Android (Chrome).
- [ ] Offline: open capture once online, go to airplane mode, record, come
      back online, and check the session uploads from the queue.
- [ ] Roster imported by CSV (`ops/ROSTER_SYNC.md`), preview read by the coach
      before import.
- [ ] Consent / wellness / coach-video screens walked through by one
      non-technical parent (scheduled right before go-live).
- [x] Billing: pilot runs on the free/manual plan. `ManualGateway` records
      plans and charges nothing. No Stripe.

## 8. Go-live day

- [ ] Deploy the tagged commit and confirm `/api/health` → `status: ok`,
      `git_sha` matches.
- [ ] Fresh backup taken by hand (`~/offdays/infra/backup.sh`) and copied off.
- [ ] Raise `OFFDAYS_AUTH_MAX_FAILURES` for the sign-up session (§2) and put it
      back afterwards.
- [ ] Someone watching the Discord alerts channel and `~/offdays-logs/` for
      the first week.
