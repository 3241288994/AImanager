#!/usr/bin/env python3
"""Install the metadata-only Mac Codex synchronizer; no account changes on install."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import uuid

from codex_device_profile import atomic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-target', required=True)
    parser.add_argument('--ssh-key', required=True, type=Path)
    parser.add_argument('--remote-helper', required=True)
    parser.add_argument('--codex-binary', required=True, type=Path)
    parser.add_argument('--proxy')
    parser.add_argument('--no-start', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('this installer is for macOS')
    # Depend on the selected interpreter explicitly, not on an interactive shell.
    import tomlkit  # noqa: F401
    from websockets.sync.client import unix_connect  # noqa: F401
    if not args.ssh_key.is_file() or not args.codex_binary.is_file():
        parser.error('SSH key and Codex executable must exist')
    home = Path.home()
    source = Path(__file__).resolve().parent
    install = home / '.local/share/aimanager/codex-device'
    state = home / '.local/state/aimanager/codex-device'
    config_path = home / '.config/aimanager/codex-device.json'
    try:
        existing = json.loads(config_path.read_text())
    except (OSError, ValueError):
        existing = {}
    for name in ['codex_device_profile.py', 'codex_device_agent.py']:
        atomic(install / name, (source / name).read_text())
    config = {**existing, 'deviceId':existing.get('deviceId') or str(uuid.uuid4()),
              'stateDir':str(state), 'codexHome':str(home/'.codex'),
              'codexBinary':str(args.codex_binary), 'sshKey':str(args.ssh_key),
              'sshTarget':args.ssh_target, 'remoteHelper':args.remote_helper}
    if args.proxy:
        config['proxy'] = args.proxy
    atomic(config_path, json.dumps(config, indent=2))
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    label = 'org.aimanager.codex-device'
    plist = home / 'Library/LaunchAgents' / (label+'.plist')
    definition = {'Label':label, 'ProgramArguments':[sys.executable, str(install/'codex_device_agent.py'), '--config', str(config_path)],
                  'RunAtLoad':True, 'KeepAlive':True, 'ThrottleInterval':30,
                  'StandardOutPath':str(state/'worker.log'), 'StandardErrorPath':str(state/'worker-error.log'),
                  'Umask':0o077}
    atomic(plist, plistlib.dumps(definition).decode())
    if not args.no_start:
        domain = 'gui/'+str(os.getuid())
        subprocess.run(['launchctl','bootout',domain+'/'+label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # launchd may return from bootout before the graceful worker shutdown has
        # released the job. Re-register only after it disappears, with a bound.
        deadline = time.monotonic()+15
        while subprocess.run(['launchctl','print',domain+'/'+label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode==0:
            if time.monotonic()>=deadline:
                raise RuntimeError('Mac synchronizer is still stopping; retry installation shortly')
            time.sleep(.25)
        while subprocess.run(['launchctl','bootstrap',domain,str(plist)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode!=0:
            if time.monotonic()>=deadline:
                raise RuntimeError('Mac synchronizer registration failed; inspect its LaunchAgent before retrying')
            time.sleep(.25)
    print('Mac Codex synchronization installed. Independent account authorization is managed in AImanager.')


if __name__ == '__main__':
    main()
