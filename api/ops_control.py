"""Additive service-token controls and durable submission leases."""
import fcntl
import hmac
import os
import signal
import threading
from fastapi import HTTPException


class JobCancelled(Exception):
    pass


def authorize(request):
    expected = os.getenv('OPS_SERVICE_TOKEN', '')
    if not expected or not hmac.compare_digest(request.headers.get('X-Service-Token', ''), expected):
        raise HTTPException(403, 'service authorization required')


def check_cancel(root):
    if (root / 'cancel.requested').exists():
        raise JobCancelled('cancel requested')


def watch_process(proc, root, stop):
    while not stop.wait(0.2):
        if (root / 'cancel.requested').exists() and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except Exception:
                    os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return


class SubmissionLease:
    def __init__(self, root):
        self.root = root

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / 'submission.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise HTTPException(409, 'submission is already in progress')
        return self

    def __exit__(self, *unused):
        self.lock.close()


class ServiceTokenMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('path','').startswith('/v1/') and os.getenv('OPS_REQUIRE_SERVICE_AUTH','false').lower() == 'true':
            from starlette.responses import JSONResponse
            headers = {k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
            expected = os.getenv('OPS_SERVICE_TOKEN','')
            if not expected or not hmac.compare_digest(headers.get('x-service-token',''),expected):
                return await JSONResponse({'detail':'service authorization required'},status_code=403)(scope,receive,send)
        await self.app(scope,receive,send)
