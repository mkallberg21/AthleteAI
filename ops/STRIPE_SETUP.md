# Stripe and the operator dashboard

The operator dashboard is one page, `https://app.0ffdays.com/admin`, that only
you can open. It shows every program, what each owes (athletes x season days x
$0.50), how far its families have got, and raises one Stripe invoice per program
per season. It is closed (404) until you run the setup below.

## How billing works

1. A director uploads a roster and sets season dates. The program appears as
   **Ready to invoice** with the amount.
2. You press **Create invoice**, typing the treasurer's email. That makes a
   **draft** in Stripe. **Nothing is sent.**
3. You press **Send invoice** (it asks you to confirm). Stripe emails the club a
   hosted page where they pay by **bank transfer or check first, card as a
   backup**.
4. Stripe tells us when it is paid (a webhook), and the row turns **Paid**.
   A check or transfer that arrives outside Stripe: **Mark paid**.
5. Kids added later show as **Catch-up invoice (N added)**: charged only for the
   days left in the season, and only once.

Never automatic: opening the dashboard only reads. An unpaid invoice shows as
**Overdue** to you; it never pauses a program or locks a child out.

## One-time setup (about 15 minutes)

### In Stripe (use TEST mode first)

1. Dashboard > **Settings > Invoices**: turn on **Bank transfer** (ACH credit
   transfer / bank debit) and card. Put bank transfer first.
2. **Developers > API keys > Create restricted key**. Give it **Write** on
   Customers, Invoices and Invoice Items; nothing else. Copy it (`rk_test_...`).
3. **Developers > Webhooks > Add endpoint**
   - URL: `https://app.0ffdays.com/api/stripe/webhook`
   - Events: `invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`,
     `invoice.voided`, `invoice.sent`, `invoice.marked_uncollectible`, `invoice.overdue`
   - Copy the **signing secret** (`whsec_...`).

### On the server

    ssh k6-server
    cd ~/offdays
    git pull
    python3 scripts/setup_stripe.py

It asks for the two secrets at hidden prompts, then prints your **operator key
once**. Save it in a password manager. If you lose it, run
`python3 scripts/setup_stripe.py --key-only` for a new one.

**Never paste a key into chat or an email.** Lose track of one: roll it in Stripe.

### Going live

Repeat with your **live** restricted key and a live webhook endpoint. The script
makes you type `LIVE` to confirm.

## Things to check before the first real invoice

- **Sales tax on software** varies by state. Ask your accountant before invoicing
  outside Tennessee. Stripe Tax collects nothing until you register.
- Send one invoice to **yourself** first and pay it by bank transfer.
- Card on a $11,000 invoice costs about 2.9% + 30c. That is why bank transfer is first.

## Safety

- The key is hashed on the server; wrong guesses are slowed and then locked out
  for 15 minutes.
- Nothing about money appears in a director's, coach's or parent's screen.
- A webhook that is not signed by Stripe changes nothing, and a retried event
  changes nothing twice.
