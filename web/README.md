# web/ — the reviewer UI (React 19, Vite, Tailwind 4)

Three-column review screens ported from Bidding-AI-expert@7e8e273 (`frontend/`),
rewritten onto the routes of [`docs/api_contract.md`](../docs/api_contract.md).
The Streamlit `frontend/` stays until S5.

| Window | Routes | Ready |
|---|---|---|
| Rules (`src/windows/RulesWindow.jsx`) | `GET /ruleset` (`?version=`), `/ruleset/versions`, `/ruleset/diff`, `/ruleset/gaps`, `PATCH`/`POST`/`DELETE /ruleset/items`, `PUT /ruleset/draft`, `POST /ruleset/confirm`, documents and pages | S3 (mock) |
| Stage I / II (`src/components/StageResultsWindow.jsx`) | `GET /projects/{pid}`, `GET /bids/{t}/results`, `POST /checks`, `GET /jobs/{id}` | S2 |
| Scoring, report | price summary, evaluation, reports | S4, not built here yet |

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
  the contract's OpenAPI schemas. Any field the schema does not name fails the test.
  The test reads `../docs/openapi.json` when it exists (after PR #27 merges), else
  `mock/openapi.s2.json`, PR #35's file (`contract/page-highlight` at `5206179`)
  trimmed to the routes the mock serves and the schemas they reference.
- openapi.json types the rule set routes as a bare dict and has no diff, gaps or item
  routes yet, so their bodies are checked against `mock/rulesetSchema.js`, the models
  of `app/rulesets/schema.py` in JS, strict on unknown fields.
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
| `VITE_API_KEY` | Sent as `X-API-Key`. Use it in development only, because a key in a browser bundle is public. |
| `VITE_API_USER` | Sent as `X-User` until per-user sessions arrive (B9). |

Page images come from the signed, short-lived `image_url` inside `BidResult` and `Page`.
The browser opens them as plain `<img>` links, and no key goes into a query string.
The API must allow the web origin through CORS.

## Tests and build

```sh
npm test             # vitest run: StageResultsWindow, RulesWindow + the mock-vs-contract check
npm run build
npm run lint         # oxlint
```

`e2e/item-l.spec.js` is a Playwright stub for the S2 check: item (l) shows in Stage I with
its page highlighted. Playwright is not a dependency yet. To run the stub, install it with
`npm i -D @playwright/test && npx playwright install chromium`, then run
`npx playwright test e2e/` against `npm run dev`.
