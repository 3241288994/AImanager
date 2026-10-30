#!/usr/bin/env python3
"""Private SSH heartbeat relay. Never exports account credentials or RPC tokens."""
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler


TERMINAL = {'completed','failed','attention','cancelled'}


def wait_for_task(value, params, rpc, wait_ms, now=time.monotonic, sleep=time.sleep):
    """Wait outside the serial RPC service, polling only metadata on loopback."""
    task=value.get('task')
    if task and task.get('state') not in TERMINAL:
        return value
    deadline=now()+min(max(wait_ms,0),8000)/1000
    while now()<deadline:
        sleep(min(.25,max(0,deadline-now())))
        device=next((d for d in rpc('codexDevices/status',{}) if d['id']==params['deviceId']),None)
        if not device:
            raise ValueError()
        if device.get('task')!=task:
            # Refresh identity metadata too, in case the target was just added.
            return rpc('codexDevices/heartbeat',params)
    return value


def main():
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError()
    params = json.loads(raw)
    if not isinstance(params, dict):
        raise ValueError()
    data = Path.home() / '.local/share/codexmanager'
    token=(data/'codexmanager.rpc-token').read_text().strip()
    http=build_opener(ProxyHandler({}))
    def rpc(method, payload):
        # Method selection is internal, never taken from the SSH caller.
        request=Request('http://127.0.0.1:48760/rpc',json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':payload}).encode(),headers={'Content-Type':'application/json','x-codexmanager-rpc-token':token})
        with http.open(request,timeout=3) as response:
            result=json.load(response)
        value=result.get('result')
        if result.get('error') or (isinstance(value,dict) and value.get('error')):
            raise ValueError()
        return value
    wait_ms=params.pop('waitMs',0)
    if not isinstance(wait_ms,int):
        raise ValueError()
    value=wait_for_task(rpc('codexDevices/heartbeat',params),params,rpc,wait_ms)
    print(json.dumps(value))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'error':'device_heartbeat_unavailable'}))
        sys.exit(1)
