// The mock in Vitest: src/test/setup.js starts this server for every test file.
import { setupServer } from "msw/node";
import { handlers } from "./handlers.js";

export const server = setupServer(...handlers);
