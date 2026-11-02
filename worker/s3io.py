"""Tiny storage helper used by the worker, clean.py and the scripts.

Every function accepts either an ``s3://bucket/key`` URI or a local file path, so the same
code runs inside the cluster (SeaweedFS through its S3 API) and on a laptop (plain files).

S3 settings come from the environment:
  S3_ENDPOINT            e.g. http://seaweedfs-s3.data.svc.cluster.local:8333
  AWS_ACCESS_KEY_ID      injected from a Kubernetes Secret, never stored in the repository
  AWS_SECRET_ACCESS_KEY  injected from a Kubernetes Secret, never stored in the repository
"""
import os
from urllib.parse import urlparse

_client = None


def is_s3(uri):
    return str(uri).startswith('s3://')


def split_s3(uri):
    """Return (bucket, key) for an s3:// URI."""
    p = urlparse(uri)
    if p.scheme != 's3' or not p.netloc:
        raise ValueError(f'not an s3:// URI: {uri}')
    return p.netloc, p.path.lstrip('/')


def client():
    """Create (once) a boto3 client for the S3 endpoint in S3_ENDPOINT."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        endpoint = os.environ.get('S3_ENDPOINT')
        if not endpoint:
            raise RuntimeError('S3_ENDPOINT is not set')
        _client = boto3.client(
            's3',
            endpoint_url=endpoint,
            region_name=os.environ.get('AWS_REGION', 'us-east-1'),
            config=Config(s3={'addressing_style': 'path'}, signature_version='s3v4',
                          retries={'max_attempts': 8, 'mode': 'standard'}),
        )
    return _client


def read_bytes(uri):
    """Return the object's bytes, or None if it does not exist."""
    if is_s3(uri):
        bucket, key = split_s3(uri)
        try:
            return client().get_object(Bucket=bucket, Key=key)['Body'].read()
        except client().exceptions.NoSuchKey:
            return None
        except Exception as e:  # SeaweedFS may answer 404 without the NoSuchKey code
            if getattr(e, 'response', {}).get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
                return None
            raise
    if not os.path.exists(uri):
        return None
    with open(uri, 'rb') as f:
        return f.read()


def read_text(uri):
    data = read_bytes(uri)
    return None if data is None else data.decode('utf-8')


def write_bytes(uri, data):
    if is_s3(uri):
        bucket, key = split_s3(uri)
        client().put_object(Bucket=bucket, Key=key, Body=data)
        return
    parent = os.path.dirname(uri)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = uri + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, uri)


def write_text(uri, text):
    write_bytes(uri, text.encode('utf-8'))


def list_uris(prefix_uri, suffix=''):
    """List objects (or files) directly under a prefix (or directory), sorted by name."""
    if is_s3(prefix_uri):
        bucket, prefix = split_s3(prefix_uri)
        if prefix and not prefix.endswith('/'):
            prefix += '/'
        out = []
        paginator = client().get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter='/'):
            for obj in page.get('Contents', []):
                if obj['Key'].endswith(suffix):
                    out.append(f's3://{bucket}/{obj["Key"]}')
        return sorted(out)
    if not os.path.isdir(prefix_uri):
        return []
    return sorted(os.path.join(prefix_uri, n) for n in os.listdir(prefix_uri)
                  if n.endswith(suffix) and os.path.isfile(os.path.join(prefix_uri, n)))


def join(prefix_uri, name):
    return prefix_uri.rstrip('/') + '/' + name
