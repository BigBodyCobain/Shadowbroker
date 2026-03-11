// All API calls use relative paths (e.g. /api/flights).
// The catch-all route handler at src/app/api/[...path]/route.ts proxies them
// to BACKEND_URL at runtime (set in docker-compose or .env.local for dev).
// This means:
//   - No build-time baking of the backend URL into the client bundle
//   - BACKEND_URL=http://backend:8000 works via Docker internal networking
//   - Only port 3000 needs to be exposed externally
export const API_BASE = "";
