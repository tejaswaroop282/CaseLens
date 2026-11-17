# CaseLens frontend

React 18 + TypeScript + Vite + Tailwind CSS 4. See the [root README](../README.md) for the project overview.

```powershell
npm install
npm run dev        # http://localhost:5173 ($env:PORT="5180"; npm run dev for another port)
npm run build      # type-check and production build into dist/
```

The API address comes from `VITE_API_BASE` (default `http://localhost:8000/api`); put an override in `.env.local`.
No secrets live in the frontend.

## Structure

| Path | What it holds |
|---|---|
| `src/lib/auth.tsx` | Session store, demo accounts, role → home page |
| `src/api/` | Typed API client (adds the bearer token; a 401 ends the session) and response types |
| `src/App.tsx` | Routes with role guards: `/owner`, `/scenarios`, `/data` for the risk owner; `/analyst`, `/alerts`, `/cases` for the analyst |
| `src/pages/` | Sign-in, owner and analyst overviews, Scenario Studio, scenario detail, Data, Alert queue, case page |
| `src/components/` | Layout (role menus), scenario editor and results, run controls, case file views, UI kit |
