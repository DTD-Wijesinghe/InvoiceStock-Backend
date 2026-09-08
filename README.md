# InvoiceStock Backend

FastAPI backend for InvoiceStock AI. Developed by D.T.D.Wijesinghe.

See [DEPLOYMENT.md](DEPLOYMENT.md) for exact Render settings, Supabase URL and required environment variables. Docker runs `python start.py`, which applies migrations and then serves the API.

Frontend repository: https://github.com/DTD-Wijesinghe/InvoiceStock-Frontend

Tests: `python -m pytest -q -p no:cacheprovider`. Tests use a disposable SQLite database unless TEST_DATABASE_URL specifies a dedicated PostgreSQL test database.
