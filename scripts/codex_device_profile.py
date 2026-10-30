"""Private per-device Codex grants and conservative native-daemon activation."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


class ProfileError(Exception):
    """Only stable, non-sensitive reason codes leave this module."""


def atomic(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_auth(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get('tokens'), dict):
            return None
        tokens = value['tokens']
        if not all(isinstance(tokens.get(key), str) and tokens[key] for key in ['id_token', 'access_token', 'refresh_token', 'account_id']):
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def claims(token):
    try:
        payload = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def identity(auth):
    if not auth:
        return None
    tokens = auth['tokens']
    data = claims(tokens['id_token'])
    entitlement = data.get('https://api.openai.com/auth')
    chatgpt = entitlement.get('chatgpt_account_id') if isinstance(entitlement, dict) else None
    if chatgpt and chatgpt != tokens['account_id']:
        return None
    if not data.get('sub'):
        return None
    keys=['workspace_id','chatgpt_account_id','organization_id','org_id']
    workspace=next((data[k].strip() for k in keys if isinstance(data.get(k),str) and data[k].strip()),None)
    if workspace is None and isinstance(entitlement,dict):
        orgs=entitlement.get('organizations')
        orgs=[x for x in orgs if isinstance(x,dict)] if isinstance(orgs,list) else []
        default=next((x for x in orgs if x.get('is_default') is True),orgs[0] if orgs else {})
        candidate=default.get('id')
        workspace=candidate.strip() if isinstance(candidate,str) and candidate.strip() else None
        workspace=workspace or next((entitlement[k].strip() for k in keys if isinstance(entitlement.get(k),str) and entitlement[k].strip()),None)
    return {'subject': data['sub'], 'chatgptAccountId': tokens['account_id'], 'workspaceId':workspace or tokens['account_id']}


def matches(auth, expected):
    observed = identity(auth)
    return bool(observed and all(observed[k] == expected.get(k) for k in observed))


def map_identity(auth, identities):
    candidates = [x for x in identities if matches(auth, x)]
    return candidates[0]['accountId'] if len(candidates) == 1 else None


def daemon_snapshot(home, check_activity=True):
    from websockets.sync.client import unix_connect
    socket = home / 'app-server-control/app-server-control.sock'
    if not socket.exists():
        return {'absent': True, 'loaded': [], 'active':False, 'email': None}
    try:
        with unix_connect(socket, open_timeout=3, close_timeout=1, max_size=1024 * 1024,
                          max_queue=8, proxy=None) as ws:
            probe_deadline=time.monotonic()+5
            def call(number, method, params):
                ws.send(json.dumps({'id':number, 'method':method, 'params':params}))
                deadline = min(probe_deadline, time.monotonic() + 4)
                for _ in range(64):
                    data = json.loads(ws.recv(timeout=max(.01, deadline - time.monotonic())))
                    if data.get('id') == number:
                        if 'error' in data:
                            raise ValueError()
                        return data['result']
                raise ValueError()
            call(1, 'initialize', {'clientInfo': {'name':'aimanager-device', 'version':'1'}, 'capabilities':{}})
            ws.send(json.dumps({'method':'initialized'}))
            loaded={'data':[],'nextCursor':None}
            statuses=[]
            if check_activity:
                loaded = call(2, 'thread/loaded/list', {'limit':128})
                if not isinstance(loaded.get('data'), list) or len(loaded['data'])>128 or loaded.get('nextCursor', 'unknown') is not None:
                    raise ValueError()
                for index,thread_id in enumerate(loaded['data']):
                    if not isinstance(thread_id,str) or not thread_id:
                        raise ValueError()
                    thread=call(index+3,'thread/read',{'threadId':thread_id,'includeTurns':False}).get('thread') or {}
                    if thread.get('id')!=thread_id:
                        raise ValueError()
                    statuses.append(thread.get('status'))
                after=call(200,'thread/loaded/list',{'limit':128})
                if after!=loaded:
                    raise ValueError()
            account = call(201, 'account/read', {'refreshToken':False}).get('account') or {}
            return {'absent':False, 'loaded':loaded['data'], 'active':activity_state(statuses), 'email':account.get('email') if account.get('type') == 'chatgpt' else None}
    except Exception:
        raise ProfileError('background_unreachable') from None


def activity_state(statuses):
    states=[x.get('type') if isinstance(x,dict) else None for x in statuses]
    if 'active' in states:
        return True
    if any(x not in ('idle','notLoaded') for x in states):
        raise ProfileError('background_unreachable')
    return False


class NativeProfile:
    def __init__(self, state: Path, home: Path):
        self.state, self.home = state, home
        self.grants = state / 'grants'
        self.grants.mkdir(parents=True, exist_ok=True, mode=0o700)

    def grant_home(self, account_id):
        return self.grants / hashlib.sha256(account_id.encode()).hexdigest()

    def capture(self, identities):
        auth = read_auth(self.home / 'auth.json')
        account = map_identity(auth, identities)
        if account:
            path = self.grant_home(account) / 'auth.json'
            stored = read_auth(path)
            latest_exp = claims(auth['tokens']['access_token']).get('exp', 0)
            old_exp = claims(stored['tokens']['access_token']).get('exp', 0) if stored else -1
            if latest_exp >= old_exp and stored != auth:
                atomic(path, json.dumps(auth))
        return account

    def known(self, identities):
        return [x['accountId'] for x in identities if matches(read_auth(self.grant_home(x['accountId']) / 'auth.json'), x)]

    def remember_intent(self, task):
        """Detect external profile changes even while waiting for authorization."""
        baseline_file = self.state / 'pending-profile.json'
        observed = identity(read_auth(self.home / 'auth.json'))
        try:
            baseline = json.loads(baseline_file.read_text())
        except (OSError, ValueError):
            baseline = {}
        if baseline.get('requestId') == task['requestId']:
            if baseline.get('identity') != observed:
                raise ProfileError('profile_changed')
        else:
            atomic(baseline_file, json.dumps({'requestId':task['requestId'], 'identity':observed}))

    def apply(self, task, expected, identities):
        current_auth = read_auth(self.home / 'auth.json')
        current_identity = identity(current_auth)
        snapshot = daemon_snapshot(self.home)
        if matches(current_auth, expected) and (snapshot['absent'] or (snapshot['email'] or '').lower() == (expected.get('email') or '').lower()):
            self.capture(identities)
            return 'completed', 'applied'
        self.remember_intent(task)
        if snapshot['active']:
            return 'pending', 'sessions_loaded'
        self.capture(identities)
        auth = read_auth(self.grant_home(expected['accountId']) / 'auth.json')
        if not matches(auth, expected):
            return 'needs_login', 'needs_login'
        # Let native Codex refresh this inactive, device-local grant when used.
        # Never refresh a copied server grant or manipulate another device's token.
        import tomlkit
        config_path, auth_path = self.home / 'config.toml', self.home / 'auth.json'
        previous_config = config_path.read_text() if config_path.exists() else None
        config = tomlkit.parse(previous_config or '')
        if config.get('model_provider') not in (None, 'openai', 'cm'):
            raise ProfileError('profile_unavailable')
        config['cli_auth_credentials_store'] = 'file'
        if config.get('model_provider') == 'cm':
            del config['model_provider']
        previous_auth = auth_path.read_text() if auth_path.exists() else None
        before = daemon_snapshot(self.home)
        if before['active']:
            return 'pending', 'sessions_loaded'
        if identity(read_auth(auth_path)) != current_identity:
            raise ProfileError('profile_changed')
        backup = self.state / 'backups' / hashlib.sha256(task['requestId'].encode()).hexdigest()
        for name, value in [('auth.json',previous_auth),('config.toml',previous_config)]:
            if value is not None:
                atomic(backup / name, value)
        auth['auth_mode'] = 'chatgpt'
        auth['OPENAI_API_KEY'] = None
        try:
            atomic(auth_path, json.dumps(auth))
            atomic(config_path, tomlkit.dumps(config))
            if not matches(read_auth(auth_path), expected):
                raise ProfileError('identity_mismatch')
        except Exception:
            for path, value in [(auth_path, previous_auth), (config_path, previous_config)]:
                if value is not None:
                    atomic(path, value)
                elif path.exists():
                    path.unlink()
            raise ProfileError('profile_unavailable') from None
        if before['absent']:
            return 'completed', 'applied'
        # Recheck after writing: another client can connect between admission and
        # activation. Never restart it then; report unverified rather than success.
        try:
            if daemon_snapshot(self.home)['active']:
                return 'attention', 'background_unverified'
            binary = self.home / 'packages/app-server-daemon/current/bin/codex'
            subprocess.run([str(binary), 'app-server','daemon','restart'],
                           env={**os.environ, 'CODEX_HOME':str(self.home)},
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, check=True)
            after = daemon_snapshot(self.home)
            if (after['email'] or '').lower() == (expected.get('email') or '').lower():
                return 'completed', 'applied'
        except Exception:
            pass
        return 'attention', 'background_unverified'
