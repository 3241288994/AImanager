#!/usr/bin/env python3
"""Mac-side, SSH-pulled account coordination. No listening HTTP port or token export."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import time

from codex_device_profile import NativeProfile, ProfileError, atomic, claims, daemon_snapshot, matches, read_auth


TERMINAL = {'completed', 'failed', 'attention', 'cancelled'}


class NativeSession:
    def __init__(self, binary, home, proxy=None):
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic(home/'config.toml', 'cli_auth_credentials_store = "file"\n')
        env = dict(os.environ)
        for key in ['OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN']:
            env.pop(key, None)
        env['CODEX_HOME'] = str(home)
        if proxy:
            env['HTTPS_PROXY'] = proxy
            env['HTTP_PROXY'] = proxy
        self.process = subprocess.Popen([str(binary), 'app-server', '--listen', 'stdio://'],
                                        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.buffer, self.number = b'', 0
        try:
            self.call('initialize', {'clientInfo':{'name':'aimanager-mac-accounts','version':'1'},'capabilities':{}}, 15)
            self.send({'method':'initialized'})
        except Exception:
            self.close()
            raise

    def send(self, value):
        try:
            self.process.stdin.write(json.dumps(value).encode()+b'\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise ProfileError('login_failed') from None

    def receive(self, timeout):
        deadline = time.monotonic()+timeout
        while b'\n' not in self.buffer:
            remaining = deadline-time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout],[],[],remaining)[0]:
                raise TimeoutError()
            data = os.read(self.process.stdout.fileno(),65536)
            if not data:
                raise ProfileError('login_failed')
            self.buffer += data
            if len(self.buffer)>2*1024*1024:
                raise ProfileError('login_failed')
        line,self.buffer = self.buffer.split(b'\n',1)
        try:
            return json.loads(line)
        except ValueError:
            raise ProfileError('login_failed') from None

    def call(self, method, params, timeout=40):
        self.number+=1
        number=self.number
        self.send({'id':number,'method':method,'params':params})
        deadline=time.monotonic()+timeout
        for _ in range(128):
            reply=self.receive(max(.01,deadline-time.monotonic()))
            if reply.get('id') == number:
                if 'error' in reply:
                    raise ProfileError('login_failed')
                return reply.get('result') or {}
        raise ProfileError('login_failed')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for stream in [self.process.stdin,self.process.stdout]:
            if stream:
                stream.close()


class Agent:
    def __init__(self, config):
        self.config=config
        self.state=Path(config['stateDir'])
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.profile=NativeProfile(self.state,Path(config['codexHome']))
        self.identities=[]
        self.report=None
        self.login=None
        self.task=None
        self.current=None
        self.sent_report=None

    def heartbeat(self, wait=False):
        self.current=self.profile.capture(self.identities)
        # Disk credentials alone do not prove the native daemon reloaded them.
        expected=next((x for x in self.identities if x['accountId']==self.current),None)
        if expected:
            try:
                snapshot=daemon_snapshot(self.profile.home,check_activity=False)
                if not snapshot['absent'] and (snapshot['email'] or '').lower()!=(expected.get('email') or '').lower():
                    self.current=None
            except ProfileError:
                self.current=None
        payload={'deviceId':self.config['deviceId'],'currentAccountId':self.current,
                 'knownAccountIds':self.profile.known(self.identities),'report':self.report,'waitMs':8000 if wait else 0}
        command=['/usr/bin/ssh','-T','-F','/dev/null','-i',self.config['sshKey'],
                 '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8',
                 '-o','ClearAllForwardings=yes','-o','ServerAliveInterval=30',
                 '-o','ControlMaster=auto','-o','ControlPersist=120',
                 '-o','ControlPath='+str(self.state/'ssh-control'),
                 self.config['sshTarget'],'python3 '+shlex.quote(self.config['remoteHelper'])]
        try:
            result=subprocess.run(command,input=json.dumps(payload).encode(),stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,timeout=20,check=True)
            if len(result.stdout)>1024*1024:
                raise ValueError()
            value=json.loads(result.stdout)
            if value.get('error') or not isinstance(value.get('identities'),list):
                raise ValueError()
            self.identities=value['identities']
            self.sent_report=json.dumps(self.report,sort_keys=True)
            atomic(self.state/'status.json',json.dumps({'updatedAt':int(time.time()),'currentAccountId':self.current,'report':self.report}))
            return value.get('task')
        except Exception:
            raise ProfileError('network_unavailable') from None

    def set_report(self, task, state, reason, **extra):
        self.report={'requestId':task['requestId'],'state':state,'reason':reason,**extra}
        # Local diagnostic state contains no permanent credentials or CLI output.
        atomic(self.state/'status.json',json.dumps({'updatedAt':int(time.time()),'currentAccountId':self.current,'report':self.report}))

    def stop_login(self):
        if self.login:
            self.login['session'].close()
            self.login=None

    def refresh_inactive_grant(self, expected):
        home=self.profile.grant_home(expected['accountId'])
        auth=read_auth(home/'auth.json')
        if claims(auth['tokens']['access_token']).get('exp',0)>time.time()+120:
            return
        # Never refresh the separate grant cache while the active CLI owns it.
        if matches(read_auth(self.profile.home/'auth.json'),expected):
            return
        session=NativeSession(self.config['codexBinary'],home,self.config.get('proxy'))
        try:
            account=session.call('account/read',{'refreshToken':True}).get('account')
            updated=read_auth(home/'auth.json')
            if not account or not matches(updated,expected) or claims(updated['tokens']['access_token']).get('exp',0)<=time.time()+30:
                raise ProfileError('credentials_invalid')
        finally:
            session.close()

    def process(self, task):
        if not task or task.get('state') in TERMINAL:
            self.stop_login()
            self.task=task
            return
        expected=next((x for x in self.identities if x['accountId']==task['accountId']),None)
        if not expected:
            self.set_report(task,'failed','identity_mismatch')
            return
        if not self.task or self.task['requestId']!=task['requestId']:
            self.stop_login()
        self.task=task
        if task['kind']=='switch' or task.get('parentRequestId'):
            self.profile.remember_intent(task)
        home=self.profile.grant_home(expected['accountId'])
        auth=read_auth(home/'auth.json')
        marker=home/'login.json'
        try:
            authorized_for_task=json.loads(marker.read_text()).get('requestId')==task['requestId']
        except (OSError,ValueError):
            authorized_for_task=False
        if self.login:
            session=self.login['session']
            try:
                if time.monotonic()>self.login['deadline']:
                    raise ProfileError('login_failed')
                else:
                    for _ in range(64):
                        try:
                            event=session.receive(.01)
                        except TimeoutError:
                            break
                        if event.get('method')=='account/login/completed':
                            params=event.get('params') or {}
                            if params.get('loginId')!=self.login['loginId']:
                                continue
                            if not params.get('success'):
                                raise ProfileError('login_failed')
                            signed_in=read_auth(self.login['home']/'auth.json')
                            if not matches(signed_in,expected):
                                raise ProfileError('identity_mismatch')
                            atomic(home/'auth.json',json.dumps(signed_in))
                            atomic(marker,json.dumps({'requestId':task['requestId']}))
                            authorized_for_task=True
                            self.stop_login()
                            break
                if self.login:
                    return
                auth=read_auth(home/'auth.json')
            except Exception:
                self.stop_login()
                raise
        if not matches(auth,expected) or (task['kind']=='login' and not authorized_for_task):
            if task['kind']!='login':
                self.set_report(task,'needs_login','needs_login')
                return
            login_home=self.state/'login-staging'/hashlib.sha256(task['requestId'].encode()).hexdigest()
            session=NativeSession(self.config['codexBinary'],login_home,self.config.get('proxy'))
            try:
                info=session.call('account/login/start',{'type':'chatgptDeviceCode'})
                code=info.get('userCode','')
                url=info.get('verificationUrl','')
                if not info.get('loginId') or url!='https://auth.openai.com/codex/device' or not (4<=len(code)<=24) or not all(c.isascii() and (c.isalnum() or c=='-') for c in code):
                    raise ProfileError('login_failed')
                self.login={'session':session,'home':login_home,'loginId':info['loginId'],'deadline':time.monotonic()+15*60}
                self.set_report(task,'authorizing','awaiting_approval',userCode=code,verificationUrl=url)
                return
            except Exception:
                session.close()
                raise
        if task['kind']=='login' and not task.get('parentRequestId'):
            self.set_report(task,'completed','authorized')
            return
        try:
            self.refresh_inactive_grant(expected)
        except ProfileError as error:
            if str(error)=='credentials_invalid':
                self.set_report(task,'needs_login','needs_login')
                return
            raise
        # Confirm the intent is still current after login/refresh before changing
        # the default. Distributed host writes are not an atomic transaction.
        fresh=self.heartbeat()
        if not fresh or fresh['requestId']!=task['requestId'] or fresh['state'] in TERMINAL:
            return
        state,reason=self.profile.apply(task,expected,self.identities)
        self.set_report(task,state,reason)

    def run(self, once=False):
        lock=(self.state/'agent.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        delay=2
        try:
            while True:
                try:
                    task=self.heartbeat(wait=True)
                    self.process(task)
                    if json.dumps(self.report,sort_keys=True)!=self.sent_report:
                        self.heartbeat()
                    atomic(self.state/'health.json',json.dumps({'updatedAt':int(time.time()),'state':'online'}))
                    delay=2 if self.task and self.task.get('state') not in TERMINAL else 0
                except Exception as error:
                    if self.task and str(error)!='network_unavailable':
                        reason=str(error) if str(error) in {'background_unreachable','identity_mismatch','credentials_invalid','profile_changed','profile_unavailable'} else 'login_failed'
                        self.stop_login()
                        self.set_report(self.task,'pending' if reason=='background_unreachable' else 'failed',reason)
                        try:
                            self.heartbeat()
                        except Exception:
                            pass
                    atomic(self.state/'health.json',json.dumps({'updatedAt':int(time.time()),'state':'offline','reason':'network_or_worker_unavailable'}))
                    delay=min(120,max(5,delay*2))
                if once:
                    return
                time.sleep(delay)
        finally:
            self.stop_login()
            lock.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    def terminate(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,terminate)
    Agent(json.loads(args.config.read_text())).run(args.once)
