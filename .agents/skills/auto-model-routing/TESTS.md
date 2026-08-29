# Auto Model Routing — pressure tests

These tests are written before `SKILL.md`.

## Baseline failure (2026-08-29)

Prompt: change a Streamlit button label, fix a Futu cache regression, and
migrate SQLite review records.

Without this skill, the agent selected one global `gpt-5.6-sol/high` route.
That over-provisions the label change and under-provisions the irreversible
persistence boundary, which must be `gpt-5.6-sol/xhigh`.

## Acceptance scenarios

1. Mixed independent work: route a cosmetic UI edit to Luna/low, a Futu
   regression to Terra, and a SQLite migration to Sol/xhigh; do not ask the
   user to choose a model.
2. Bounded safe change: route a one-file copy or label edit to Luna/low.
3. New evidence: after discovering persistence, security, broker/order, or
   transaction scope, automatically re-route upward without a user approval.
4. The automatic policy must not select Sol/ultra; it is reserved for an
   explicit human decision.

## Green evidence (2026-08-29)

The first skill-run exposed two wording defects: a UI label could be mistaken
for a public programmatic interface, and `Sol/ultra` could be read as blocking
all automatic Sol routes. The rules now exclude visual labels from the public
contract signal and reserve only the `ultra` reasoning effort for explicit
human choice. The rerun must route the three scenarios to Luna/low,
Terra/high (two paths add 5), and Sol/xhigh, respectively.
