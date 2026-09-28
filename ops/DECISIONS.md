# Decisions log

What has been decided about how 0FFDAYS is hosted, monitored, emailed and
run, and why. **Read this before proposing infrastructure.** Anything not
listed here is open. When a decision changes, edit its entry and date it;
don't add a contradicting one further down.

Last updated: 2026-09-28.

---

## Email: Resend over SMTP. Not SES, not SNS.

- **Decision.** Outbound mail (guardian invites, coach digest, parent
  report) goes through **Resend** over plain SMTP, the same provider
  UtiliTrust uses (`smtp.resend.com:587`, user `resend`, the API key as the
  password). The sending domain is `mail.0ffdays.com`.
- **Not AWS.** Do **not** set up SES, SNS topics, or the OCSP stapling job
  for this. The SES/SNS code in `offdays/sns.py`, `chain.py`,
  `revocation.py` and `staple.py` stays in the repo, switched off:
  `OFFDAYS_SNS_TOPIC_ARNS` is blank (that disables the endpoint), and
  `refresh_staples.py` is commented out in `infra/crontab.offdays`. It was
  built for a possible SES setup and isn't needed.
- **Bounce webhooks: off for the pilot.** The webhook module verifies
  SendGrid, Postmark, Mailgun and SES, **not Resend** (Resend signs webhooks
  with Svix). At pilot volume (about 35 families) a bounce is something a
  coach notices. If bounce handling is needed later, add a Resend verifier
  to `offdays/webhooks.py`. Don't switch providers to get it.
- **Status: not set up yet.** Needed:
  1. Add `mail.0ffdays.com` in Resend. The free plan allows one domain, which
     is probably already used by `mail.utilitrust.com`, so this is either a
     second free Resend account or the paid plan. Free is capped at 100/day
     and 3,000/month.
  2. Add Resend's DKIM/SPF records in Cloudflare, plus
     `_dmarc.0ffdays.com` TXT `v=DMARC1; p=none; rua=mailto:<you>`.
  3. The apex `0ffdays.com` has `v=spf1 -all` (sends nothing). That's
     correct as long as mail goes from the `mail.` subdomain. Leave it.
  4. Fill in the `OFFDAYS_SMTP_*` values in `~/offdays/infra/.env.prod` on
     k6-server and redeploy.
- **UtiliTrust, same finding:** there's no DMARC record on `utilitrust.com`
  or `mail.utilitrust.com`. Add `_dmarc.utilitrust.com` TXT
  `v=DMARC1; p=none; rua=mailto:<you>`.

## Monitoring: Uptime Kuma, alerts to Discord

- **Decision.** Uptime Kuma (self-hosted) posts alerts to the team's Discord
  channel through a webhook.
- **Why not UptimeRobot:** its free plan alerts one recipient only, and the
  whole team needs to hear about downtime.
- **Why not Prometheus/Grafana (yet):** too much for a single pilot. On a
  box shared with UtiliTrust it's hundreds of MB for numbers `/api/health`
  already reports. Revisit on the utility server (below) once there's more
  than one program.
- **Where it runs today:** Podman on Matt's workstation (**not** the box the
  agent works from), localhost:3001. Linger and `podman-restart.service` are
  enabled. **Not yet confirmed that it survives a reboot.**
- **Monitors:**

  | Monitor | URL | Check |
  |---|---|---|
  | 0FFDAYS ready | `https://app.0ffdays.com/api/ready` | keyword `"ready":true` |
  | 0FFDAYS live | `https://app.0ffdays.com/api/live` | keyword `"live":true` |
  | UtiliTrust app | `https://app.utilitrust.com` | HTTP 200 |

  All at 60 s, 2 retries 30 s apart, certificate-expiry alerts on.
- **Known gap:** if the workstation is off or offline, nothing alerts and
  nobody is told. The planned fix is a healthchecks.io dead-man switch (a
  Kuma monitor pings it every 60 s, and it posts to the same Discord webhook
  when the pings stop). **Not set up yet.**
- **SMS: later.** Every Kuma SMS provider is paid (Twilio, ClickSend, a cent
  or two per message). Carrier email-to-text gateways are being shut down,
  so don't build on them.
- **Planned move:** Kuma goes to the utility server (below) when that exists.
  The monitor list above moves with it unchanged.

## Utility server (planned, not built)

A small always-on box, separate from k6-server, for things that shouldn't
live on a workstation or on the production box:

- Uptime Kuma (moved from the workstation), so monitoring doesn't share a
  failure with what it monitors.
- The Hermes agent gateway.
- Later: Grafana/Prometheus, and an off-box backup target for k6-server.

Likely shape: a Hetzner CX22-class VPS (2 vCPU / 4 GB, about €4–5/mo),
joined to the tailnet with k6-server. Nothing is decided beyond "we need
one".

## Hosting: k6-server, next to UtiliTrust

- Hetzner VPS `178.156.233.148`, SSH port 2222, user `jason`. Ubuntu 24.04,
  4 vCPU, 7.6 GB. It also runs UtiliTrust and n8n.
- 0FFDAYS runs as one rootless Podman container, `offdays_app_1`, on
  `127.0.0.1:8810`, behind the host's nginx
  (`/etc/nginx/sites-enabled/offdays`) with a Let's Encrypt certificate
  (auto-renewed by the box's certbot timer). UtiliTrust owns 8801–8806.
- One uvicorn worker, SQLite in WAL mode on the `offdays_data` volume. The
  server does no pose inference (that runs on the phones), so a 35-athlete
  pilot needs no more capacity. Watch disk: `/` was 67% full, mostly
  UtiliTrust.
- Config lives in `~/offdays/infra/.env.prod` on the server (mode 600, never
  committed).

## Deploys: GitHub Actions

- `CI` runs on every push. `Deploy` runs only after CI passes on `main`, or
  by hand from the Actions tab. `infra/deploy.sh` refuses to deploy if
  `OFFDAYS_SECRET` or `OFFDAYS_BASE_URL` is blank, waits for `/api/live` to
  report the new commit, then reinstalls the cron block.
- The deploy key is `github-actions-deploy@offdays` and belongs to this
  repo only (UtiliTrust has its own).
- `deploy.sh` needs `rsync`, so run it from CI or WSL, not Git Bash.

## DNS: Cloudflare for 0ffdays.com

- The domain is still **registered at Squarespace**. Its nameservers now
  point to Cloudflare (the same account as utilitrust.com).
- `app.0ffdays.com` is an A record to `178.156.233.148`, **DNS only (grey
  cloud)**. It must stay grey: behind Cloudflare's proxy every family would
  appear to come from a Cloudflare address, and the sign-in throttle would
  lock them out together. Proxying it would first need nginx `real_ip` with
  Cloudflare's IP ranges.
- `0ffdays.com` and `www` point to Squarespace's "Coming Soon" page, through
  Cloudflare's proxy. **That's intentional:** the marketing site stays
  separate from the app, the same split as UtiliTrust. Families get the
  `app.` link in their invite.

## Backups

- Nightly at 03:47 UTC: `infra/backup.sh` takes an online SQLite backup plus
  an integrity check, gzips it to `~/offdays-backups/`, and keeps 14 days.
  Verified by hand on 2026-09-28.
- **Only on the same disk so far.** Set `OFFSITE` to an rclone remote
  (Hetzner Storage Box about €4/mo, or the utility server) to copy it off
  the box. A restore drill hasn't been done yet.
- `BACKUP_HEARTBEAT_URL` can point at a Kuma Push monitor or
  healthchecks.io, so a missed night alerts Discord.

## Product and pilot decisions

| Topic | Decision | Where |
|---|---|---|
| Billing | No Stripe for the pilot. `ManualGateway` records the plan and charges nothing. | `offdays/billing.py` |
| Roster | CSV upload for Nashville Dogs. TeamSnap/SportsEngine adapters are unverified. | `ops/ROSTER_SYNC.md` |
| Guardian verification | **Open.** Recommended: A + D for the pilot (codes handed out in person, short expiry, coach approves each guardian), then B (emailed link) before a second program. | `ops/GUARDIAN_VERIFICATION.md` |
| Consent / parent walkthrough | Done right before go-live. | checklist §7 |
| Rep-count accuracy | Needs at least 6 own-youth wall-ball clips per drill through `/app/calibrate.html`, then `calibration.verdict()`. | README "Known limitations" #7 |
| Coach video | Consent stays off for the pilot unless a guardian asks. Clips are unencrypted in SQLite. | README "Known limitations" #1 |
