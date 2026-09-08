"""Production entrypoint: migrate once, then serve on the provider PORT."""
import os
from pathlib import Path

def main():
    os.chdir(Path(__file__).resolve().parent)
    try:
        from app.db import settings, engine
        if engine.dialect.name != 'postgresql' or settings.demo_mode:
            raise ValueError('Production requires PostgreSQL and DEMO_MODE=false.')
        from alembic.config import Config
        from alembic import command
        command.upgrade(Config('alembic.ini'), 'head')
        engine.dispose()
    except Exception as error:
        # Never echo a database URL or settings input containing secrets.
        print('Startup failed ('+type(error).__name__+'). Check DATABASE_URL/password/TLS, JWT_SECRET (32+ characters), and migration SQL files. See DEPLOYMENT.md.', flush=True)
        raise SystemExit(1) from None
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT','8000')))

if __name__=='__main__': main()
