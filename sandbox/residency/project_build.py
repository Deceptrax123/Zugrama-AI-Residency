"""Actual multi-file project builds in a confined process, with bounded receipts."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import selectors
import signal
import subprocess
import sys
import threading
import time

from .config import APP_ROOT

PYTHON_ROOT = APP_ROOT / '.tools/project-build-venv'
NODE_ROOT = APP_ROOT / '.tools/hermes-runtime/node-26.12.1-linux-x64'
JS_ROOT = APP_ROOT / '.tools/project-node-runtime'
WORKER = APP_ROOT / 'scripts/project_build_worker.py'
BUILD_GATE = threading.BoundedSemaphore(2)


def safe_path(value):
    if not isinstance(value, str) or not value or len(value) > 200 or '\\' in value or '\0' in value:
        raise ValueError('Use a short relative project path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.parts[0] in ('node_modules', 'tmp') or any(part.startswith('.') for part in path.parts):
        raise ValueError('Project files must remain below the build workspace')
    return str(path)


def sources_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def execute(files, command, directory, timeout=45):
    if not isinstance(files, dict) or len(files) > 128 or len(json.dumps(files).encode()) > 2_000_000:
        raise ValueError('Use at most 128 source files and 2 MB of source')
    for path, content in files.items():
        safe_path(path)
        if not isinstance(content, str):
            raise ValueError('Source files must be text')
    if not isinstance(command, list) or not 1 <= len(command) <= 20 or any(not isinstance(v, str) or '\0' in v or len(v) > 16000 for v in command):
        raise ValueError('Use a bounded argv array, not a shell command')
    commands = {
        'python': [str(PYTHON_ROOT / 'bin/python')],
        'pytest': [str(PYTHON_ROOT / 'bin/python'), '-m', 'pytest'],
        'node': [str(NODE_ROOT / 'bin/node')],
        'npm': [str(NODE_ROOT / 'bin/node'), str(NODE_ROOT / 'lib/node_modules/npm/bin/npm-cli.js')],
        'tsc': [str(NODE_ROOT / 'bin/node'), str(JS_ROOT / 'node_modules/typescript/bin/tsc')],
        'esbuild': [str(JS_ROOT / 'node_modules/@esbuild/linux-x64/bin/esbuild')],
        'gcc': ['/usr/bin/gcc'], 'make': ['/usr/bin/make'],
    }
    if command[0] not in commands or not Path(commands[command[0]][0]).exists():
        raise ValueError('Choose an installed Python, JS/TS, gcc or make build command')
    argv = commands[command[0]] + command[1:]
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    for path, content in files.items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    if 'pytest.ini' not in files:
        (directory / 'pytest.ini').write_text('[pytest]\n')
    # The exposed node_modules link resolves only to read-only runtime libraries.
    (directory / 'node_modules').symlink_to(JS_ROOT / 'node_modules', target_is_directory=True)
    (directory / 'tmp').mkdir()
    env = {'PATH': str(PYTHON_ROOT / 'bin') + ':' + str(NODE_ROOT / 'bin') + ':/usr/bin:/bin',
           'HOME': str(directory), 'TMPDIR': str(directory / 'tmp'),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
           'NODE_PATH': str(JS_ROOT / 'node_modules'), 'OMP_NUM_THREADS': '1',
           'OPENSSL_CONF': '/dev/null', 'NODE_OPTIONS': '--max-old-space-size=512 --disable-wasm-trap-handler',
           'PYTEST_ADDOPTS': '-c pytest.ini --rootdir=.',
           'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'MPLCONFIGDIR': str(directory / 'tmp')}
    packet = {'work': str(directory), 'argv': argv, 'runtimes': [str(PYTHON_ROOT), str(NODE_ROOT), str(JS_ROOT)], 'environment': env}
    started = time.monotonic()
    output = bytearray()
    reason = None
    with BUILD_GATE:
        child = subprocess.Popen([sys.executable, '-I', '-B', str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=directory, env={'PATH': '/usr/bin:/bin'}, close_fds=True, start_new_session=True)
        try:
            child.stdin.write(json.dumps(packet).encode())
            child.stdin.close()
            deadline = time.monotonic() + min(timeout, 60)
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while selector.get_map() and reason is None:
                    if time.monotonic() >= deadline:
                        reason = 'wall_clock_limit'
                        break
                    for key, _ in selector.select(.1):
                        data = os.read(key.fd, 8192)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        output.extend(data)
                        if len(output) > 64000:
                            reason = 'output_limit'
                            break
            if reason is None:
                child.wait(timeout=1)
        finally:
            # Descendants cannot escape the process group in the syscall policy.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            child.stdout.close()
    return {'ok': reason is None and child.returncode == 0, 'exit_code': child.returncode,
            'output': output[:64000].decode(errors='replace'), 'limit': reason,
            'seconds': round(time.monotonic() - started, 3), 'command': command,
            'source_sha256': sources_digest(files), 'sandbox': 'landlock-seccomp-build/v1',
            'network_access': False, 'meaning': 'Executed command receipt; passing alone is not proof of project completion.'}
