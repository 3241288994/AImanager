#!/usr/bin/env python3
"""Black-box switch regression with a real Service and a fake Codex daemon.

Usage: python3 scripts/tests/probe_codex_account_switch.py /path/to/codexmanager-service
Uses only synthetic credentials, an isolated SQLite DB/profile, and loopback RPC.
The daemon implements just the documented JSON-RPC methods used by the guard.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_device_rpc import wait_for_task
from urllib.request import Request, build_opener, ProxyHandler


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return 'e30.' + encoded + '.test-signature'


def read_exact(stream, size):
    data = b''
    while len(data) < size:
        block = stream.recv(size - len(data))
        if not block:
            raise EOFError()
        data += block
    return data


class Daemon:
    def __init__(self, profile):
        self.profile = profile
        self.loaded = True
        self.active = True
        self.identity_ready = True
        self.socket = socket.socket(socket.AF_UNIX)
        path = profile / 'app-server-control/app-server-control.sock'
        path.parent.mkdir()
        self.socket.bind(str(path))
        self.socket.listen()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while True:
            try:
                stream, _ = self.socket.accept()
            except OSError:
                return
            with stream:
                stream.settimeout(5)
                try:
                    header = b''
                    while not header.endswith(b'\r\n\r\n'):
                        header += read_exact(stream, 1)
                    key = next(line.split(':', 1)[1].strip() for line in header.decode().splitlines()
                               if line.lower().startswith('sec-websocket-key:'))
                    accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                    stream.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode())
                    while True:
                        first, length = read_exact(stream, 2)
                        if first & 15 == 8:
                            break
                        masked, size = length & 128, length & 127
                        if size == 126:
                            size = struct.unpack('!H', read_exact(stream, 2))[0]
                        elif size == 127:
                            size = struct.unpack('!Q', read_exact(stream, 8))[0]
                        assert size <= 16384
                        mask = read_exact(stream, 4) if masked else b''
                        data = read_exact(stream, size)
                        if masked:
                            data = bytes(value ^ mask[i % 4] for i, value in enumerate(data))
                        request = json.loads(data)
                        if 'id' not in request:
                            continue
                        method = request['method']
                        if method == 'thread/loaded/list':
                            result = {'data': ['loaded-thread'] if self.loaded else [], 'nextCursor': None}
                        elif method == 'thread/read':
                            assert request['params'].get('includeTurns') is False
                            result = {'thread':{'id':request['params']['threadId'],'status':{'type':'active' if self.active else 'idle','activeFlags':[]}}}
                        elif method == 'account/read':
                            account = json.loads((self.profile / 'auth.json').read_text())['tokens']['account_id']
                            result = {'account': {'type': 'chatgpt', 'email': account + '@example.invalid'} if self.identity_ready else None}
                        else:
                            assert method == 'initialize'
                            result = {}
                        data = json.dumps({'id': request['id'], 'result': result}).encode()
                        stream.sendall(bytes([129, len(data)]) + data if len(data) < 126 else b'\x81\x7e' + struct.pack('!H', len(data)) + data)
                except (EOFError, OSError):
                    pass


def main(binary):
    binary = str(Path(binary).resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix='aim-switch-', dir='/tmp') as directory:
        root = Path(directory)
        profile = root / 'profile'
        profile.mkdir()
        db = root / 'test.db'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'CODEX_HOME': str(profile),
               'CODEXMANAGER_DB_PATH': str(db), 'CODEXMANAGER_RPC_TOKEN': 'isolated-test-token',
               'CODEXMANAGER_SERVICE_ADDR': f'127.0.0.1:{port}',
               'CODEXMANAGER_USAGE_POLLING_ENABLED': 'false',
               'CODEXMANAGER_TOKEN_REFRESH_POLLING_ENABLED': 'false',
               'CODEXMANAGER_GATEWAY_KEEPALIVE_ENABLED': 'false'}
        http = build_opener(ProxyHandler({}))
        process = None
        log = (root / 'service.log').open('w')

        def rpc(method, params=None, error=False):
            request = Request(f'http://127.0.0.1:{port}/rpc',
                              json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}).encode(),
                              headers={'Content-Type': 'application/json', 'x-codexmanager-rpc-token': 'isolated-test-token'})
            with http.open(request, timeout=15) as response:
                value = json.load(response)
            result = value.get('result')
            failure = value.get('error') or (result.get('error') if isinstance(result,dict) else None)
            if error:
                assert failure, method
                return value
            assert not failure, (method, failure)
            return value['result']

        def start():
            nonlocal process
            process = subprocess.Popen([binary], env=env, cwd=root, stdout=log, stderr=log)
            for _ in range(100):
                assert process.poll() is None, 'isolated service exited'
                try:
                    rpc('codexProfile/get')
                    return
                except OSError:
                    time.sleep(.1)
            raise AssertionError('isolated service did not start')

        def stop():
            nonlocal process
            if process:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process = None

        def apply(account):
            return rpc('codexProfile/applyDirectAccount', {'accountId': account})

        def wait_state(state):
            for _ in range(100):
                value = rpc('codexProfile/get')
                if value['accountSwitch']['state'] == state:
                    return value
                time.sleep(.25)
            raise AssertionError('queue did not reach ' + state + ': ' + json.dumps(value['accountSwitch']))

        daemon = None
        try:
            start()
            stop()
            now = int(time.time())
            with sqlite3.connect(db) as conn:
                for account in ['a', 'b']:
                    identity = jwt({'sub': account, 'email': account + '@example.invalid'})
                    access = jwt({'sub': account, 'exp': now + 86400})
                    conn.execute('INSERT INTO accounts(id,label,issuer,chatgpt_account_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                                 [account, account + '@example.invalid', 'http://127.0.0.1:1', account, 'active', now, now])
                    conn.execute('INSERT INTO tokens(account_id,id_token,access_token,refresh_token,last_refresh) VALUES(?,?,?,?,?)',
                                 [account, identity, access, 'test-refresh-' + account, now])
            start()
            assert apply('a')['accountSwitch']['state'] == 'completed'
            auth = profile / 'auth.json'
            value = json.loads(auth.read_text())
            value['tokens']['access_token'] = jwt({'sub': 'a', 'exp': now + 172800})
            value['tokens']['refresh_token'] = 'test-rotated-a'
            auth.write_text(json.dumps(value))
            unchanged = auth.read_bytes()
            daemon = Daemon(profile)
            restart = profile / 'packages/app-server-daemon/current/bin/codex'
            restart.parent.mkdir(parents=True)
            restart.write_text('#!/bin/sh\nexit 0\n')
            restart.chmod(0o700)

            first = apply('b')['accountSwitch']
            assert first['state'] == 'pending' and first['reason'] == 'sessions_loaded'
            assert auth.read_bytes() == unchanged
            assert apply('b')['accountSwitch']['requestId'] == first['requestId'], 'duplicate clicks must preserve request scope'
            second = apply('a')['accountSwitch']
            assert second['requestId'] != first['requestId']
            rpc('codexProfile/cancelSwitch', {'requestId': first['requestId']}, error=True)
            assert rpc('codexProfile/get')['accountSwitch']['requestId'] == second['requestId']
            assert rpc('codexProfile/cancelSwitch', {'requestId': second['requestId']})['accountSwitch'] is None
            assert auth.read_bytes() == unchanged
            print('PASS loaded-session guard, latest-intent replacement and scoped cancellation', flush=True)

            pending = apply('b')['accountSwitch']
            stop()
            start()
            assert rpc('codexProfile/get')['accountSwitch']['requestId'] == pending['requestId']
            assert auth.read_bytes() == unchanged
            daemon.active = False
            result = wait_state('completed')
            assert result['selectedAccountId'] == 'b' and result['identityConsistent']
            with sqlite3.connect(db) as conn:
                assert conn.execute('SELECT refresh_token FROM tokens WHERE account_id=?', ['a']).fetchone()[0] == 'test-rotated-a'
                assert conn.execute('SELECT refresh_token FROM tokens WHERE account_id=?', ['b']).fetchone()[0] == 'test-refresh-b'
            assert apply('a')['accountSwitch']['state'] == 'completed'
            assert json.loads(auth.read_text())['tokens']['refresh_token'] == 'test-rotated-a'
            assert daemon.loaded, 'idle thread remains open while switching'
            print('PASS loaded-but-idle threads switch, durable queue resumes and rotated credentials survive', flush=True)

            daemon.identity_ready = False
            pending = apply('b')['accountSwitch']
            assert pending['state']=='pending' and pending['reason']=='background_unverified'
            switched = auth.read_bytes()
            stop(); start()
            assert rpc('codexProfile/get')['accountSwitch']['requestId']==pending['requestId']
            daemon.identity_ready = True
            assert wait_state('completed')['selectedAccountId']=='b'
            assert auth.read_bytes()==switched, 'verification retries must not rewrite credentials'
            assert apply('a')['accountSwitch']['state']=='completed'
            print('PASS delayed background login stays pending, survives restart and recovers without rewriting auth',flush=True)

            daemon.loaded = True
            daemon.active = True
            pending = apply('b')['accountSwitch']
            with sqlite3.connect(db) as conn:
                pending['requestedAt'] = now - 86400
                conn.execute('UPDATE app_settings SET value=? WHERE key=?', [json.dumps(pending), 'codex_profile.account_switch'])
            before = auth.read_bytes()
            assert wait_state('failed')['accountSwitch']['reason'] == 'expired'
            assert auth.read_bytes() == before
            print('PASS expired requests stop without changing credentials', flush=True)

            mac = {'deviceId':'synthetic-mac-device','currentAccountId':'a','knownAccountIds':['a']}
            paired = rpc('codexDevices/heartbeat',mac)
            assert paired['task'] is None
            rpc('codexDevices/heartbeat',{'deviceId':mac['deviceId']})
            assert rpc('codexDevices/status')[0]['currentAccountId']=='a', 'bootstrap must preserve last identity'
            assert all(set(item)=={'accountId','subject','chatgptAccountId','workspaceId','email'} for item in paired['identities'])
            delivered=[]
            receiver=threading.Thread(target=lambda:delivered.append(wait_for_task(paired,mac,rpc,8000)))
            receiver.start()
            time.sleep(.1)
            requested_at=time.monotonic()
            pending = rpc('codexProfile/applyDirectAccount',{'accountId':'b','syncDevices':True})['accountSwitch']
            receiver.join(timeout=2)
            assert not receiver.is_alive() and delivered[0].get('task') and delivered[0]['task']['parentRequestId']==pending['requestId'], {'delivered':delivered,'pending':pending}
            assert time.monotonic()-requested_at<2, 'long poll must wake without a full heartbeat delay'
            assert pending['syncDevices'] and pending['state']=='pending'
            task = rpc('codexDevices/heartbeat',mac)['task']
            assert task['parentRequestId']==pending['requestId'] and task['accountId']=='b'
            report={'requestId':task['requestId'],'state':'completed','reason':'applied','refreshToken':'must-not-persist'}
            ack = rpc('codexDevices/heartbeat',dict(mac,report=report))
            assert ack['task']['state']=='pending', 'wrong current identity cannot complete Mac switch'
            assert 'must-not-persist' not in json.dumps(rpc('codexDevices/status'))
            ack = rpc('codexDevices/heartbeat',dict(mac,report=dict(report,state='needs_login',reason='needs_login')))
            assert ack['task']['state']=='needs_login'
            stop(); start()
            assert rpc('codexDevices/status')[0]['task']['requestId']==task['requestId']
            rpc('codexProfile/cancelSwitch',{'requestId':pending['requestId']})
            assert rpc('codexDevices/status')[0]['task']['state']=='cancelled'
            login = rpc('codexDevices/login',{'deviceId':mac['deviceId'],'accountId':'b'})[0]['task']
            assert login['parentRequestId'] is None
            done = rpc('codexDevices/heartbeat',dict(mac,knownAccountIds=['a','b'],report={'requestId':login['requestId'],'state':'completed','reason':'authorized'}))
            assert done['task']['state']=='completed'
            assert rpc('codexProfile/get')['selectedAccountId']=='a', 'authorization alone cannot switch the default'
            print('PASS metadata-only Mac pairing, independent auth, partial state, restart and cancellation',flush=True)

            with sqlite3.connect(db) as conn:
                conn.execute('INSERT INTO account_subscriptions(account_id,has_subscription,plan_type,account_plan_type,expires_at,updated_at) VALUES(?,?,?,?,?,?)', ['b',1,'pro','pro',now+86400,now])
                confirmation=json.dumps({'b':{'monthlyUsd':200,'expiresAt':now+86400}})
                conn.execute('INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)',['codex_profile.pro_tiers',confirmation,now])
            def price():
                return next(x for x in rpc('account/list')['items'] if x['id']=='b')['planMonthlyUsd']
            assert price()==200
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE account_subscriptions SET account_plan_type='free' WHERE account_id='b'")
            assert price() is None
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE account_subscriptions SET account_plan_type='pro',expires_at=? WHERE account_id='b'",[now+172800])
            assert price() is None
            print('PASS wake-on-request delivery and period-bound Pro tier price, without changing Free entitlements',flush=True)
        finally:
            stop()
            if daemon:
                daemon.socket.close()
            log.close()


if __name__ == '__main__':
    main(sys.argv[1])
