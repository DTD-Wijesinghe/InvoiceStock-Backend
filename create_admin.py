"""Trusted CLI provisioning only. The public registration API cannot create admins."""
import getpass
from sqlalchemy import select
from app.db import SessionLocal,User,Business
from app.main import hasher

def main():
    email=input('Administrator email: ').strip().lower()
    name=input('Administrator name: ').strip()
    if '@' not in email or len(name)<2:raise SystemExit('Valid email and name required.')
    password=getpass.getpass('Password (at least 14 characters): ')
    confirm=getpass.getpass('Confirm password: ')
    if len(password)<14 or password!=confirm:raise SystemExit('Passwords must match and contain at least 14 characters.')
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email==email)):raise SystemExit('Email already exists. No account changed.')
        business=Business(name='Platform administration')
        db.add(business);db.flush()
        db.add(User(business_id=business.id,name=name,email=email,password_hash=hasher.hash(password),role='platform_admin'))
    print('Platform administrator created. Use the normal sign-in form.')

if __name__=='__main__':main()
