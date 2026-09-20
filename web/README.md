# web/ — the reviewer UI (React 19, Vite, Tailwind 4)

Three-column review screens ported from Bidding-AI-expert@7e8e273 (`frontend/`),
rewritten onto the routes of [`docs/api_contract.md`](../docs/api_contract.md).
The Streamlit `frontend/` stays until S5.

| Window | Routes | Ready |
|---|---|---|
| Rules (`src/windows/RulesWindow.jsx`) | `GET /ruleset`, `POST /ruleset/confirm`, documents and pages | S2 |
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
- `mock/handlers.js` holds the routes, plus a page image drawn as SVG. With
  `?highlight=` it draws the highlight box, as the real PNG route does.
- `mock/contract.test.js` fetches every mocked route and checks the body against
  the contract's OpenAPI schemas. Any field the schema does not name fails the test.
  The test reads `../docs/openapi.json` when it exists (after PR #27 merges), else
  `mock/openapi.s2.json`, a trimmed snapshot of PR #27's file at `c0e3813`.
- The rule set fixture is checked against the pydantic model with:
  `python -c "import json; from app.rulesets.schema import RuleSet; RuleSet.model_validate(json.load(open('web/mock/fixtures/ruleset.json')))"`

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
npm test             # vitest run: StageResultsWindow + the mock-vs-contract check
npm run build
npm run lint         # oxlint
```

`e2e/item-l.spec.js` is a Playwright stub for the S2 check: item (l) shows in Stage I with
its page highlighted. Playwright is not a dependency yet. To run the stub, install it with
`npm i -D @playwright/test && npx playwright install chromium`, then run
`npx playwright test e2e/` against `npm run dev`.
