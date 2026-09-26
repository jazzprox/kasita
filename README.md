# Kasita

Self-hosted household pantry: shopping list, pantry with expiry dates, barcode
scanning and receipt scanning, shared per household. Server + web app + Android app.

- `server/`: FastAPI + Postgres API (`/docs` for the interactive API reference)
- `app/`: Flutter app (Android + web), coming next

## Server quick start

```bash
cd server
docker build -t kasita-server .
docker run -e KASITA_DATABASE_URL=postgresql+psycopg://... -e KASITA_SECRET_KEY=... -p 8000:8000 kasita-server
docker exec -it <container> python -m app.cli create-admin --email you@example.com --name You --household Home
```

There is no public sign-up: the first account comes from `create-admin`, everyone
else joins a household through an invite.

## Barcode lookup order

1. the household's own products (instant, includes local brands you named once)
2. Open Food Facts, Open Products Facts, Open Beauty Facts
3. UPCitemdb free tier (100 lookups/day)

Answers from 2–3 are cached for 30 days.

## Tests

```bash
cd server && pip install ".[test]" && pytest
```
