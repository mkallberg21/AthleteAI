# Club badges

Drop a program's logo here as a PNG or SVG, then point the organization at it:

```python
store.set_org_logo(org_id, "nashville-dogs.png")
```

It appears at the top of every screen that program sees — the coach dashboard,
the athlete's capture screen, the parent view and the leaderboard — at 72px
tall, with the 0FFDAYS mark behind it as a credit line.

A club opens this app to train for *their* club. Their badge leads; ours sits
behind it. A program with no badge uploaded gets its name in the same place,
so the header is never empty and never looks like it belongs to us.

## Sizing

`.club-badge` is set in `styles.css` from the aspect of the badge actually
shipped here, not from a guess. The demo crest is 2000x714 (2.80:1), so 72px
tall renders it 202px wide against our 120px lockup. A much squarer badge
would need that height raised again to keep leading -- the test measures it.

## What is here now

- `nashville-dogs.png` -- the demo program's real crest, supplied by the club.
- `sample-badge.svg` -- a neutral placeholder the tests point at.

There is deliberately no *approximation* of any club's crest. A drawing that
is nearly somebody's logo is worse than their name set in the product's own
type, which is what a program with no badge uploaded gets.
