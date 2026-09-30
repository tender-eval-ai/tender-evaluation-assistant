# web/ — the reviewer UI (React 19, Vite, Tailwind 4)

Three-column review screens ported from Bidding-AI-expert@7e8e273 (`frontend/`),
rewritten onto the routes of [`docs/api_contract.md`](../docs/api_contract.md).
It is the project's only UI: `docker compose up` serves it on :8080 (`web/Dockerfile`).

Every window is built, and every route it calls is served by `backend/`; the mock
answers the same routes for development without a backend.

| Window | Routes | Served by |
|---|---|---|
| Rules (`src/windows/RulesWindow.jsx`) | `GET /ruleset` (`?version=`), `/ruleset/versions`, `/ruleset/diff`, `/ruleset/gaps`, `PATCH`/`POST`/`DELETE /ruleset/items`, `PUT /ruleset/draft`, `POST /ruleset/confirm`, documents and pages | `backend/routes/rulesets.py` |
| Stage I / II (`src/windows/StageIWindow.jsx`, `StageIIWindow.jsx`, both on `src/components/StageResultsWindow.jsx`) | `GET /projects/{pid}`, `GET /bids/{t}/results`, `POST /checks`, `GET /jobs/{id}`, `PATCH /bids/{t}/fields/{letter}/{field}` (a reviewer's correction), `POST /bids/{t}/review/confirm` | `backend/routes/results.py`, `backend/routes/review.py` |
| Scoring (`src/windows/ScoringWindow.jsx`) | `GET /price-summary` | `backend/routes/pricing.py` |
| Report (`src/windows/ReportWindow.jsx`) | `GET /evaluation`, `GET /reports`, `GET /reports/{name}` (the Word files) | `backend/routes/pricing.py`, `backend/routes/reports.py` |

## Run on the mock

```sh
cd web
npm ci
npm run dev          # http://localhost:5173, served by web/mock/
```

Without `VITE_API_BASE` the app starts [MSW](https://mswjs.io) in a service worker
(`public/mockServiceWorker.js`) and `web/mock/handlers.js` answers every call on the
page's own origin. The top bar shows "mock API". The data is the synthetic
SYN-2026-001 case from `test/data/synthetic_tender`: four tenderers. Tenderer_A passes item (l)
on p.10 of its offer. Tenderer_C has no certificate, so (l) disqualifies. Tenderer_B has
no result until you press "Run check".

- `mock/fixtures.js` and `mock/fixtures/ruleset.json` hold every response in one place.
- `mock/rulesetStore.js` keeps the rule sets in memory: v1 confirmed
  (`fixtures/ruleset.json`) and a v2 draft (`fixtures/ruleset_draft.json`) in which
  item (c) needs input and gap `Supp:13:(d)` has no reason, so v2 cannot be confirmed
  until both are dealt with. Every edit needs a reason and records who and when; a
  corrected slot keeps the model's value in `model_value`; the last editor of a draft
  gets `403 self_approval` on confirm. The top of the Rules window has an "acting as"
  box on the mock (sent as `X-User`) so one browser can edit as one person and
  confirm as another. A reload starts from the fixtures again.
- Adding an item: page images have no text layer, so the clause is picked with a
  citation picker (document, page, optional clause node, verbatim text typed or taken
  from text selected anywhere in the window) rather than by selecting on the image.
- `mock/handlers.js` holds the routes, plus a page image drawn as SVG. With
  `?highlight=` it draws the highlight box, as the real PNG route does. The image
  link is signed as `backend/signing.py` does it (PR #35): a citation with a
  `quote` has `highlight` inside the signature, so a changed highlight gets 403;
  a page-only link still takes an unsigned highlight (the Rules window's tender
  quotes, until S3). Scanned offers (Tenderer_B, Tenderer_D) have no text layer:
  their citations have null `quote`/`box`/`page_size` and nothing is marked.
- `mock/contract.test.js` fetches every mocked route and checks the body against
  the contract's OpenAPI schemas (`../docs/openapi.json`). Any field the schema does
  not name fails the test.
- The rule set bodies are also checked against `mock/rulesetSchema.js`, the models of
  `app/rulesets/schema.py` in JS, strict on unknown fields.
- The rule set fixtures are checked against the pydantic model with:
  `python -c "import json; from app.rulesets.schema import RuleSet; [RuleSet.model_validate(json.load(open(f'web/mock/fixtures/{f}'))) for f in ('ruleset.json', 'ruleset_draft.json')]"`

## Point at the real API

```sh
VITE_API_BASE=http://localhost:8000 VITE_API_USER=nasi npm run dev
```

| Variable | Meaning |
|---|---|
| `VITE_API_BASE` | API origin. When it is set, the mock is off. |
| `VITE_API_MOCK` | `1` or `0` forces the mock on or off, for example `0` with the API behind the same origin. |
| `VITE_REPLAY` | `1`: the guest site. Every GET is answered from a recorded run under `public/replay/` (`tools/record_run.py`; `.github/workflows/pages.yml` fetches the newest `replay-*` release), and every change is refused. |
| `VITE_REPLAY_LABEL` | What the top bar shows instead of "mock API", e.g. `Recorded run · 1 October 2026` (the recording's `manifest.json` has it). |
| `VITE_API_KEY` | Sent as `X-API-Key`. Use it in development only, because a key in a browser bundle is public. |
| `VITE_API_USER` | Sent as `X-User` until per-user sessions arrive (B9). |

Page images come from the signed, short-lived `image_url` inside `BidResult` and `Page`.
The browser opens them as plain `<img>` links, and no key goes into a query string.
The API must allow the web origin through CORS.

## Tests and build

```sh
npm test             # vitest run: every window, the review corrections + the mock-vs-contract check
npm run build
npm run lint         # oxlint
npx playwright install chromium   # once
npm run e2e          # Playwright, in a real browser on the mock
```

Playwright (`@playwright/test`) is a dev dependency, and CI runs `npm run e2e` in the
`e2e` job. `playwright.config.js` starts `npm run dev` itself; set `WEB_URL` to use a
server that is already running, or start the dev server with `VITE_API_BASE` to run the
same steps against the real API.

- `e2e/item-l.spec.js`: the S2 check. Item (l) shows in Stage I with its page highlighted.
- `e2e/review-flow.spec.js`: the S4 review flow. The rules, a check run, a field the
  reviewer corrects and the verdict changing with it, the review confirmed, then the
  Scoring and Report windows, down to the report download.
