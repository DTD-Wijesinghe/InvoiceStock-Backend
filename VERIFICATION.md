# Deployment verification — 2026-09-08

- Backend: 33 passed, 1 skipped. The skipped test requires a dedicated PostgreSQL concurrency-test database. Two dependency deprecation warnings.
- Checked Supabase URL normalization to psycopg, encoded passwords, required TLS, and placeholder rejection.
- Checked all three frozen SQL inputs resolve inside this standalone backend repository.
- Frontend: TypeScript and Vite production build passed. Vercel Build Output API v3 package generated successfully with an explicit synthetic HTTPS backend origin.
- Checked API routes precede static/SPA routes, API responses use no-store, and index/assets exist. Invalid HTTP backend origins correctly fail the build.
- No Netlify configuration remains in the frontend repository.
- Real Supabase connectivity, Linux Docker image execution, hosted Vercel proxy/cookies and live Render deployment have not been verified. Real credentials/provider access were not supplied in the request.
- No Git commits or pushes made. Windows denied Git index writes; run Prepare-Git.ps1 locally before committing to untrack ignored databases/caches without deleting local copies.
