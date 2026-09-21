"""Private object storage helpers with database fallback."""
from urllib.parse import quote
import httpx
from .db import settings


def r2_ready():
    return all((settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket_name, settings.r2_endpoint))


def supabase_ready():
    return bool(settings.supabase_url and settings.supabase_service_role_key and settings.supabase_storage_bucket)


def put_r2(key, content, content_type):
    try:
        import boto3
        client = boto3.client('s3', endpoint_url=settings.r2_endpoint, aws_access_key_id=settings.r2_access_key_id,
                              aws_secret_access_key=settings.r2_secret_access_key, region_name='auto')
        client.put_object(Bucket=settings.r2_bucket_name, Key=key, Body=content, ContentType=content_type)
        return 'r2', key
    except Exception:
        return '', ''


def get_r2(key):
    import boto3
    client = boto3.client('s3', endpoint_url=settings.r2_endpoint, aws_access_key_id=settings.r2_access_key_id,
                          aws_secret_access_key=settings.r2_secret_access_key, region_name='auto')
    return client.get_object(Bucket=settings.r2_bucket_name, Key=key)['Body'].read()


def put_supabase(key, content, content_type):
    if not supabase_ready():
        return '', ''
    url = settings.supabase_url.rstrip('/') + '/storage/v1/object/' + quote(settings.supabase_storage_bucket, safe='') + '/' + quote(key, safe='/')
    response = httpx.post(url, content=content, headers={'Authorization': 'Bearer ' + settings.supabase_service_role_key,
                       'apikey': settings.supabase_service_role_key, 'Content-Type': content_type, 'x-upsert': 'true'}, timeout=30)
    response.raise_for_status()
    return 'supabase', key


def get_supabase(key):
    url = settings.supabase_url.rstrip('/') + '/storage/v1/object/' + quote(settings.supabase_storage_bucket, safe='') + '/' + quote(key, safe='/')
    response = httpx.get(url, headers={'Authorization': 'Bearer ' + settings.supabase_service_role_key,
                       'apikey': settings.supabase_service_role_key}, timeout=30)
    response.raise_for_status()
    return response.content


def put_large(key, content, content_type):
    if r2_ready():
        provider, storage_key = put_r2(key, content, content_type)
        if provider:
            return provider, storage_key
    return '', ''


def put_small(key, content, content_type):
    if supabase_ready():
        try:
            return put_supabase(key, content, content_type)
        except Exception:
            pass
    return '', ''


def read(provider, key):
    if provider == 'r2':
        return get_r2(key)
    if provider == 'supabase':
        return get_supabase(key)
    return None
