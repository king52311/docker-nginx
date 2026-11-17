#!/usr/bin/env python3
"""Apply versioned Docker HEALTHCHECKs while preserving exact live images/config.
Default is read-only planning. --apply recreates one container at a time.
Backups include credentials: keep backup root private and outside Git.
"""
import argparse
import copy
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.parse

class Docker:
    def call(self, method, path, body=None, allow=()):
        class UnixHTTP(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(180)
                self.sock.connect('/var/run/docker.sock')
        conn = UnixHTTP('localhost', timeout=180)
        raw = None if body is None else json.dumps(body).encode()
        conn.request(method, '/v1.52' + path, raw, {'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        if response.status >= 300 and response.status not in allow:
            # Engine messages may echo environment values: never print raw body.
            raise RuntimeError(f'Docker {method} {path.split("?")[0]} failed ({response.status})')
        return json.loads(data) if data else None
    def inspect(self, name):
        return self.call('GET', '/containers/' + name + '/json')

def create_body(old, health, binary, revision):
    cfg = copy.deepcopy(old['Config'])
    cfg['Image'] = old['Image']  # Immutable image; never refresh a floating tag.
    cfg['Healthcheck'] = health
    cfg.setdefault('Labels', {})['com.snuday.health.revision'] = revision
    host = copy.deepcopy(old['HostConfig'])
    # Explicitly retain anonymous/named volumes, never allocate replacements.
    bound = {s.split(':')[1] for s in host.get('Binds') or [] if ':' in s}
    bound.update(m['Target'] for m in host.get('Mounts') or [])
    for m in old.get('Mounts', []):
        if m['Destination'] in bound:
            continue
        source = m['Name'] if m['Type'] == 'volume' else m['Source']
        if m['Type'] in ('bind', 'volume'):
            host.setdefault('Binds', [])
            host['Binds'] = (host['Binds'] or []) + [source + ':' + m['Destination'] + (':rw' if m.get('RW') else ':ro')]
    if binary:
        host['Binds'] = [b for b in host.get('Binds') or [] if b.split(':')[1] != '/opt/container-health/probe']
        host['Binds'].append(str(binary) + ':/opt/container-health/probe:ro')
    endpoints = {}
    if host.get('NetworkMode') not in ('host', 'none'):
        for name, e in old['NetworkSettings']['Networks'].items():
            aliases = [a for a in e.get('Aliases') or [] if a not in (old['Id'], old['Id'][:12])]
            ep = {'Aliases': aliases}
            if e.get('IPAMConfig'):
                ep['IPAMConfig'] = e['IPAMConfig']
            endpoints[name] = ep
    return dict(cfg, HostConfig=host, NetworkingConfig={'EndpointsConfig': endpoints})

def wait_healthy(docker, name, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        c = docker.inspect(name)
        if not c['State']['Running']:
            raise RuntimeError(name + ' exited')
        state = c['State'].get('Health', {}).get('Status')
        if state == 'healthy':
            return c
        if state == 'unhealthy':
            raise RuntimeError(name + ' unhealthy')
        time.sleep(2)
    raise RuntimeError(name + ' health timeout')

def apply_one(docker, name, health, binary, revision, backup_dir, timeout=150):
    old = docker.inspect(name)
    if old['Config'].get('Healthcheck') == health and (not binary or any(m.get('Source') == str(binary) for m in old['Mounts'])):
        wait_healthy(docker, name, timeout)
        print(name + ': already healthy', flush=True)
        return {'name': name, 'id': old['Id'], 'image': old['Image'], 'changed': False}
    if not old['State']['Running']:
        raise RuntimeError(name + ' is not running; refusing to start an inactive service')
    body = create_body(old, health, binary, revision)
    # Reject container sharing modes; these require handling dependent IDs.
    if old['HostConfig'].get('NetworkMode', '').startswith('container:') or old['HostConfig'].get('PidMode', '').startswith('container:'):
        raise RuntimeError('Shared container namespace requires explicit migration')
    save = backup_dir / name
    save.mkdir(mode=0o700)
    (save / 'inspect.json').write_text(json.dumps(old))
    backup_name = name + '-health-backup-' + str(int(time.time()))
    new_id = None
    stopped = False
    renamed = False
    disconnected = []
    try:
        docker.call('POST', '/containers/' + old['Id'] + '/stop?t=60')
        stopped = True
        docker.call('POST', '/containers/' + old['Id'] + '/rename?name=' + backup_name)
        renamed = True
        # Disable restart of an obsolete singleton before creating its replacement.
        docker.call('POST', '/containers/' + old['Id'] + '/update', {'RestartPolicy': {'Name': 'no'}})
        for network in old['NetworkSettings']['Networks']:
            if old['HostConfig']['NetworkMode'] not in ('host', 'none'):
                docker.call('POST', '/networks/' + network + '/disconnect', {'Container': old['Id'], 'Force': True})
                disconnected.append(network)
        new_id = docker.call('POST', '/containers/create?name=' + urllib.parse.quote(name), body)['Id']
        docker.call('POST', '/containers/' + new_id + '/start')
        current = wait_healthy(docker, new_id, timeout)
        assert current['Image'] == old['Image']
        # All original persistent mounts must still point to the same source.
        old_mounts = {(m['Destination'], m['Source']) for m in old['Mounts']}
        assert old_mounts <= {(m['Destination'], m['Source']) for m in current['Mounts']}
    except BaseException:
        if new_id:
            docker.call('DELETE', '/containers/' + new_id + '?force=true', allow=(404,))
        if renamed:
            docker.call('POST', '/containers/' + old['Id'] + '/rename?name=' + urllib.parse.quote(name))
        for network in disconnected:
            ep = old['NetworkSettings']['Networks'][network]
            if old['HostConfig']['NetworkMode'] not in ('host', 'none'):
                endpoint = {'Aliases': ep.get('Aliases') or []}
                if ep.get('IPAMConfig'):
                    endpoint['IPAMConfig'] = ep['IPAMConfig']
                docker.call('POST', '/networks/' + network + '/connect', {'Container': old['Id'], 'EndpointConfig': endpoint})
        docker.call('POST', '/containers/' + old['Id'] + '/update', {'RestartPolicy': old['HostConfig']['RestartPolicy']})
        if stopped:
            docker.call('POST', '/containers/' + old['Id'] + '/start')
        raise RuntimeError(name + ': check failed; original container restored') from None
    # Remove obsolete container only after successful health and mount checks.
    docker.call('DELETE', '/containers/' + old['Id'])
    receipt = {'name': name, 'id': new_id, 'image': old['Image'], 'changed': True, 'health': 'healthy'}
    (save / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(name + ': healthy', flush=True)
    return receipt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--backup-root', type=Path, default=Path('/data/docker-health/backups'))
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    revision = subprocess.check_output(['git', '-C', str(here), 'rev-parse', 'HEAD'], text=True).strip()
    # Require exact committed health source. Existing nginx runtime config is separate.
    status = subprocess.check_output(['git', '-C', str(here), 'status', '--porcelain', '--', '.'], text=True)
    if status.strip():
        raise SystemExit('Health source has uncommitted changes')
    if args.apply:
        args.backup_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock = (args.backup_root / '.apply.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for project in ('/home/docker/findme', '/home/docker/admin_findme'):
            if (Path(project) / '.deploy/update.lock').exists():
                raise SystemExit('Project deployment is running; retry after completion')
    specs = json.loads((here / 'checks.json').read_text())
    docker = Docker()
    live = docker.call('GET', '/containers/json?all=true')
    targets = {n.lstrip('/'): c for c in live for n in c['Names']}
    unknown = set(targets) - set(specs)
    if unknown and not args.only:
        raise SystemExit('Missing probe definitions: ' + ', '.join(sorted(unknown)))
    selected = args.only or list(specs)
    if set(selected) - set(targets):
        raise SystemExit('Specified container is absent')
    if not args.binary.is_file() or not os.access(args.binary, os.X_OK):
        raise SystemExit('Static Linux probe binary is required')
    receipts = []
    os.umask(0o077)
    backup = args.backup_root / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + str(os.getpid()))
    if args.apply:
        backup.mkdir(parents=True, mode=0o700)
    for name in selected:
        spec = specs[name]
        old = docker.inspect(name)
        existing = old['Config'].get('Healthcheck')
        if spec.get('preserve_existing'):
            if not existing or existing.get('Test', ['NONE'])[0] == 'NONE':
                raise SystemExit(name + ': expected existing health check is missing')
            if args.apply:
                wait_healthy(docker, name, 150)
            print(name + ': existing check retained', flush=True)
            continue
        command = spec['test']
        health = {'Test': command, 'Interval': 30_000_000_000, 'Timeout': 10_000_000_000,
                  'Retries': 3, 'StartPeriod': 30_000_000_000}
        binary = args.binary.resolve() if '/opt/container-health/probe' in command else None
        if args.apply:
            receipts.append(apply_one(docker, name, health, binary, revision, backup))
        else:
            print(name + ': needs health check' if existing != health else name + ': configured', flush=True)
    if args.apply:
        (backup / 'summary.json').write_text(json.dumps({'revision': revision, 'probe_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(), 'containers': receipts}, indent=2))
        print('Health checks applied; private receipts: ' + str(backup))

if __name__ == '__main__':
    main()
