"""Wait until the SeaweedFS S3 API answers through the k3d NodePort (used by `make storage`)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s3tool  # noqa: E402

deadline = time.time() + 300
while True:
    try:
        s3tool.client().list_buckets()
        print('S3 API is answering')
        break
    except Exception as e:  # noqa: BLE001
        if time.time() > deadline:
            sys.exit(f'S3 API not answering: {e!r}')
        print(f'waiting for S3: {type(e).__name__}', flush=True)
        time.sleep(3)
