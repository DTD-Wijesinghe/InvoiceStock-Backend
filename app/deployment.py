"""Normalize hosted database URLs without exposing credentials in errors."""
from sqlalchemy.engine import make_url

def database_url(value):
    value=value.strip()
    if value.startswith('postgres://'): value='postgresql+psycopg://'+value[len('postgres://'):]
    elif value.startswith('postgresql://'): value='postgresql+psycopg://'+value[len('postgresql://'):]
    url=make_url(value)
    if url.get_backend_name()=='postgresql':
        if not url.password or 'YOUR-PASSWORD' in url.password or 'REPLACE_' in url.password:
            raise ValueError('DATABASE_URL requires the real database password, URL-encoded.')
        if url.host and url.host.endswith('supabase.com'):
            url=url.update_query_dict({'sslmode':'require'})
    return url
