// The mock in the browser: `npm run dev` without VITE_API_BASE starts this
// service worker (public/mockServiceWorker.js) before the app renders.
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers.js";

export const worker = setupWorker(...handlers);
