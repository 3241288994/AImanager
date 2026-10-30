import base64
import json
from pathlib import Path
import sys
import tempfile
import importlib.util
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_device_agent as agent
import codex_device_profile as profile
from codex_device_rpc import wait_for_task


def auth(subject='one', account='workspace-one'):
    def jwt(value):
        return 'x.' + base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=') + '.x'
    return {'tokens':{'id_token':jwt({'sub':subject, 'https://api.openai.com/auth':{'chatgpt_account_id':account}}),
                      'access_token':jwt({'exp':9999999999}), 'refresh_token':'fixture-only', 'account_id':account}}


ONE = {'accountId':'local-one', 'subject':'one', 'chatgptAccountId':'workspace-one', 'workspaceId':'workspace-one', 'email':'one@example.invalid'}
TWO = {'accountId':'local-two', 'subject':'two', 'chatgptAccountId':'workspace-two', 'workspaceId':'workspace-two', 'email':'two@example.invalid'}
TASK = {'requestId':'fixture-request', 'accountId':'local-two', 'kind':'switch', 'state':'pending', 'parentRequestId':'root'}
ABSENT = {'absent':True, 'loaded':[], 'active':False, 'email':None}
HAS_TOMLKIT = importlib.util.find_spec('tomlkit') is not None


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = profile.NativeProfile(self.root/'state', self.root/'codex')
        profile.atomic(self.native.home/'auth.json', json.dumps(auth()))
        profile.atomic(self.native.home/'config.toml', '# retained\nmodel = "fixture"\n')

    def save_target(self):
        profile.atomic(self.native.grant_home(TWO['accountId'])/'auth.json', json.dumps(auth('two','workspace-two')))

    def test_identity_requires_both_subject_and_workspace(self):
        self.assertTrue(profile.matches(auth(), ONE))
        self.assertFalse(profile.matches(auth(), TWO))
        self.assertFalse(profile.matches(auth(),dict(ONE,workspaceId='other-workspace')))
        self.assertIsNone(profile.map_identity(auth(),[ONE,dict(ONE,accountId='duplicate')]))
        invalid = auth(); invalid['tokens']['account_id']='unexpected'
        self.assertIsNone(profile.identity(invalid))
        self.assertEqual(profile.claims('x.W10.x'),{})
        for raw in ['[]','{"tokens":[]}','{"tokens":null}']:
            profile.atomic(self.root/'malformed.json',raw)
            self.assertIsNone(profile.read_auth(self.root/'malformed.json'))

    def test_import_only_local_matching_credentials_private(self):
        self.assertEqual(self.native.capture([ONE,TWO]),ONE['accountId'])
        self.assertEqual(self.native.known([ONE,TWO]),[ONE['accountId']])
        path = self.native.grant_home(ONE['accountId'])/'auth.json'
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertFalse((self.native.grant_home(TWO['accountId'])/'auth.json').exists())

    def test_active_sessions_defer_without_writes_or_restart(self):
        self.save_target()
        original = (self.native.home/'auth.json').read_bytes()
        with patch.object(profile,'daemon_snapshot',return_value={'absent':False,'loaded':['active'],'active':True,'email':ONE['email']}), patch.object(profile.subprocess,'run') as run:
            self.assertEqual(self.native.apply(TASK,TWO,[ONE,TWO]),('pending','sessions_loaded'))
            run.assert_not_called()
        self.assertEqual((self.native.home/'auth.json').read_bytes(),original)

    def test_same_identity_is_a_noop_even_with_loaded_sessions(self):
        with patch.object(profile,'daemon_snapshot',return_value={'absent':False,'loaded':['active'],'active':True,'email':ONE['email']}), patch.object(profile.subprocess,'run') as run:
            self.assertEqual(self.native.apply(dict(TASK,accountId=ONE['accountId']),ONE,[ONE,TWO]),('completed','applied'))
            run.assert_not_called()

    @unittest.skipUnless(HAS_TOMLKIT, 'optional Mac runtime tomlkit is not installed')
    def test_switch_uses_device_local_grant_and_keeps_configuration(self):
        self.save_target()
        with patch.object(profile,'daemon_snapshot',return_value=ABSENT):
            self.assertEqual(self.native.apply(TASK,TWO,[ONE,TWO]),('completed','applied'))
        self.assertTrue(profile.matches(profile.read_auth(self.native.home/'auth.json'),TWO))
        config = (self.native.home/'config.toml').read_text()
        self.assertIn('# retained',config)
        self.assertIn('model = "fixture"',config)
        self.assertIn('cli_auth_credentials_store = "file"',config)

    def test_external_identity_change_while_waiting_is_not_overwritten(self):
        self.native.remember_intent(TASK)
        profile.atomic(self.native.home/'auth.json',json.dumps(auth('third','workspace-third')))
        with patch.object(profile,'daemon_snapshot',return_value=ABSENT):
            with self.assertRaisesRegex(profile.ProfileError,'profile_changed'):
                self.native.apply(TASK,TWO,[ONE,TWO])

    @unittest.skipUnless(HAS_TOMLKIT, 'optional Mac runtime tomlkit is not installed')
    def test_unverifiable_daemon_is_not_success(self):
        self.save_target()
        snapshots = [{'absent':False,'loaded':[],'active':False,'email':ONE['email']}]*3
        with patch.object(profile,'daemon_snapshot',side_effect=snapshots), patch.object(profile.subprocess,'run',side_effect=OSError('fixture')):
            self.assertEqual(self.native.apply(TASK,TWO,[ONE,TWO]),('attention','background_unverified'))

    def test_activity_status_allows_idle_but_guards_approval_and_unknown(self):
        self.assertFalse(profile.activity_state([{'type':'idle'},{'type':'notLoaded'}]))
        self.assertTrue(profile.activity_state([{'type':'active','activeFlags':['waitingOnApproval']}]))
        for status in [None,{}, {'type':'systemError'}, {'type':'future'}]:
            with self.assertRaisesRegex(profile.ProfileError,'background_unreachable'):
                profile.activity_state([status])

    def test_ssh_wait_uses_only_metadata_and_refreshes_on_changed_intent(self):
        now=[0.0]
        def sleep(seconds): now[0]+=seconds
        value={'task':None,'identities':[]}
        expected={'task':TASK,'identities':[ONE,TWO]}
        rpc=Mock(side_effect=[[{'id':'fixture','task':TASK}],expected])
        self.assertEqual(wait_for_task(value,{'deviceId':'fixture'},rpc,8000,lambda:now[0],sleep),expected)
        self.assertEqual(now[0],.25)
        self.assertEqual([c.args[0] for c in rpc.call_args_list],['codexDevices/status','codexDevices/heartbeat'])

    def test_pending_tasks_do_not_wait_and_idle_wait_has_a_hard_bound(self):
        rpc=Mock()
        value={'task':TASK}
        self.assertEqual(wait_for_task(value,{'deviceId':'fixture'},rpc,8000),value)
        rpc.assert_not_called()
        now=[0.0]
        rpc.return_value=[{'id':'fixture','task':None}]
        def sleep(seconds): now[0]+=seconds
        value={'task':None}
        self.assertEqual(wait_for_task(value,{'deviceId':'fixture'},rpc,999999,lambda:now[0],sleep),value)
        self.assertEqual(now[0],8)

    @unittest.skipUnless(HAS_TOMLKIT, 'optional Mac runtime tomlkit is not installed')
    def test_loaded_idle_sessions_switch_without_waiting_for_exit(self):
        self.save_target()
        idle={'absent':False,'loaded':['still-open'],'active':False,'email':ONE['email']}
        after=dict(idle,email=TWO['email'])
        with patch.object(profile,'daemon_snapshot',side_effect=[idle,idle,idle,after]), patch.object(profile.subprocess,'run') as run:
            self.assertEqual(self.native.apply(TASK,TWO,[ONE,TWO]),('completed','applied'))
            run.assert_called_once()

    @unittest.skipUnless(HAS_TOMLKIT, 'optional Mac runtime tomlkit is not installed')
    def test_task_starting_after_write_prevents_restart(self):
        self.save_target()
        idle={'absent':False,'loaded':['still-open'],'active':False,'email':ONE['email']}
        with patch.object(profile,'daemon_snapshot',side_effect=[idle,idle,dict(idle,active=True)]), patch.object(profile.subprocess,'run') as run:
            self.assertEqual(self.native.apply(TASK,TWO,[ONE,TWO]),('attention','background_unverified'))
            run.assert_not_called()

    @unittest.skipUnless(HAS_TOMLKIT, 'optional Mac runtime tomlkit is not installed')
    def test_atomic_write_failure_restores_previous_profile(self):
        self.save_target()
        previous=(self.native.home/'auth.json').read_bytes()
        real=profile.atomic
        failed=False
        def fail_once(path,value):
            nonlocal failed
            if path==self.native.home/'config.toml' and not failed:
                failed=True
                raise OSError('fixture')
            return real(path,value)
        with patch.object(profile,'daemon_snapshot',return_value=ABSENT), patch.object(profile,'atomic',side_effect=fail_once):
            with self.assertRaisesRegex(profile.ProfileError,'profile_unavailable'):
                self.native.apply(TASK,TWO,[ONE,TWO])
        self.assertEqual((self.native.home/'auth.json').read_bytes(),previous)

    def make_agent(self):
        value=agent.Agent({'stateDir':str(self.root/'agent'), 'codexHome':str(self.native.home),'codexBinary':'/fixture/codex'})
        value.identities=[ONE,TWO]
        return value

    def test_missing_grant_requests_login_without_automatic_oauth(self):
        value=self.make_agent()
        with patch.object(agent,'NativeSession') as session:
            value.process(TASK)
            session.assert_not_called()
        self.assertEqual(value.report['state'],'needs_login')

    def test_superseded_intent_cannot_change_default(self):
        value=self.make_agent()
        profile.atomic(value.profile.grant_home(TWO['accountId'])/'auth.json',json.dumps(auth('two','workspace-two')))
        with patch.object(value,'heartbeat',return_value=dict(TASK,requestId='newer')), patch.object(value.profile,'apply') as apply:
            value.process(TASK)
            apply.assert_not_called()

    def test_explicit_login_always_uses_isolated_staging_and_official_url(self):
        value=self.make_agent()
        profile.atomic(value.profile.grant_home(TWO['accountId'])/'auth.json',json.dumps(auth('two','workspace-two')))
        native=Mock()
        native.call.return_value={'loginId':'fixture-login','userCode':'TEST-ONLY','verificationUrl':'https://auth.openai.com/codex/device'}
        with patch.object(agent,'NativeSession',return_value=native) as session:
            value.process(dict(TASK,kind='login'))
            self.assertIn('login-staging',str(session.call_args.args[1]))
        self.assertEqual(value.report['state'],'authorizing')
        self.assertFalse('refresh_token' in json.dumps(value.report))
        value.stop_login()

    def test_wrong_authorized_account_never_overwrites_existing_grant(self):
        value=self.make_agent()
        task=dict(TASK,kind='login')
        value.task=task
        native=Mock()
        native.receive.return_value={'method':'account/login/completed','params':{'loginId':'fixture','success':True}}
        staging=self.root/'staging'
        profile.atomic(staging/'auth.json',json.dumps(auth()))
        value.login={'session':native,'home':staging,'loginId':'fixture','deadline':float('inf')}
        original=(self.native.home/'auth.json').read_bytes()
        with self.assertRaisesRegex(profile.ProfileError,'identity_mismatch'):
            value.process(task)
        self.assertFalse((value.profile.grant_home(TWO['accountId'])/'auth.json').exists())
        self.assertEqual((self.native.home/'auth.json').read_bytes(),original)


if __name__ == '__main__':
    unittest.main()
