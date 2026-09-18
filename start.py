"""Production entrypoint: migrate once, then serve on the provider PORT."""
import os
from pathlib import Path


def bootstrap_admin():
    """Create/update one administrator when explicit deployment secrets are supplied.

    The password is read only from the hosting environment and is never written to
    source control or printed. Remove ADMIN_PASSWORD after the deployment succeeds.
    """
    email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    password = os.environ.get('ADMIN_PASSWORD', '')
    if not email or not password:
        return
    if '@' not in email or len(password) < 14:
        raise ValueError('ADMIN_EMAIL must be valid and ADMIN_PASSWORD must contain at least 14 characters.')

    from sqlalchemy import select
    from pwdlib import PasswordHash
    from app.db import SessionLocal, User, Business

    hasher = PasswordHash.recommended()
    name = os.environ.get('ADMIN_NAME', 'D.T.D.Wijesinghe').strip() or 'D.T.D.Wijesinghe'
    with SessionLocal.begin() as db:
        admin = db.scalar(select(User).where(User.role == 'platform_admin').order_by(User.created_at))
        if admin is None:
            business = Business(name='Platform administration')
            db.add(business)
            db.flush()
            admin = User(business_id=business.id, email=email, name=name,
                         password_hash=hasher.hash(password), role='platform_admin')
            db.add(admin)
        else:
            admin.email = email
            admin.name = name
            admin.password_hash = hasher.hash(password)
    print('Administrator bootstrap completed.', flush=True)

def main():
    os.chdir(Path(__file__).resolve().parent)
    try:
        from app.db import settings, engine
        if engine.dialect.name != 'postgresql' or settings.demo_mode:
            raise ValueError('Production requires PostgreSQL and DEMO_MODE=false.')
        from alembic.config import Config
        from alembic import command
        command.upgrade(Config('alembic.ini'), 'head')
        bootstrap_admin()
        engine.dispose()
    except Exception as error:
        # Never echo a database URL or settings input containing secrets.
        print('Startup failed ('+type(error).__name__+'). Check DATABASE_URL/password/TLS, JWT_SECRET (32+ characters), and migration SQL files. See DEPLOYMENT.md.', flush=True)
        raise SystemExit(1) from None
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT','8000')))

if __name__=='__main__': main()
