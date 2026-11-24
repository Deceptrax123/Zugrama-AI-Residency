"""Trusted Linux loader: confine project builds with Landlock and seccomp."""
import ctypes
import ctypes.util
import errno
import json
import os
import resource
import sys


def restrict_files(work, runtimes):
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Landlock ABI 3 or newer is required; build denied')

    class Ruleset(ctypes.Structure):
        _fields_ = [('fs', ctypes.c_uint64), ('net', ctypes.c_uint64), ('scoped', ctypes.c_uint64)]

    class Beneath(ctypes.Structure):
        _fields_ = [('access', ctypes.c_uint64), ('parent', ctypes.c_int32)]

    fs = (1 << (16 if abi >= 5 else 15)) - 1
    attr = Ruleset(fs, 0, 3 if abi >= 6 else 0)
    size = ctypes.sizeof(attr) if abi >= 6 else 16 if abi >= 4 else 8
    ruleset = libc.syscall(444, ctypes.byref(attr), size, 0)
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), 'Cannot create build filesystem policy')
    try:
        paths = [(work, fs)]
        paths += [(p, 1 | 4 | 8) for p in ['/usr', '/bin', '/lib', '/lib64', *runtimes] if os.path.isdir(p)]
        paths += [(p, 4) for p in ['/etc/ld.so.cache', '/etc/localtime', '/proc/cpuinfo',
                                  '/proc/meminfo', '/proc/stat', '/proc/sys/kernel/osrelease'] if os.path.isfile(p)]
        paths += [(p, 2 | 4) for p in ['/dev/null', '/dev/urandom'] if os.path.exists(p)]
        for path, access in paths:
            descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Beneath(access, descriptor)
                if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
                    raise OSError(ctypes.get_errno(), 'Cannot add build filesystem rule')
            finally:
                os.close(descriptor)
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, ruleset, 0) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot activate build filesystem policy')
    finally:
        os.close(ruleset)


def restrict_syscalls():
    library = 'libseccomp.so.2'
    seccomp = ctypes.CDLL(library, use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    policy = seccomp.seccomp_init(0x7fff0000)
    if not policy:
        raise RuntimeError('Cannot create build syscall policy')
    try:
        for name in ('socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
                     'ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd',
                     'mount', 'umount2', 'pivot_root', 'chroot', 'unshare', 'setns',
                     'bpf', 'perf_event_open', 'io_uring_setup', 'io_uring_enter', 'io_uring_register',
                     'open_by_handle_at', 'name_to_handle_at', 'keyctl', 'add_key', 'request_key',
                     'setsid', 'setpgid', 'kill', 'tkill', 'tgkill', 'pidfd_send_signal',
                     'reboot', 'kexec_load', 'init_module', 'finit_module', 'delete_module'):
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and seccomp.seccomp_rule_add(policy, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError('Cannot configure build syscall policy')
        if seccomp.seccomp_load(policy) != 0:
            raise RuntimeError('Cannot activate build syscall policy')
    finally:
        seccomp.seccomp_release(policy)


def main():
    packet = json.loads(sys.stdin.buffer.read(32000))
    work = packet['work']
    os.chdir(work)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    # Linux counts every task for this UID, including unrelated app services.
    tasks = 0
    for process in os.scandir('/proc'):
        if process.name.isdigit():
            try:
                if process.stat().st_uid == os.getuid():
                    tasks += len(os.listdir(process.path + '/task'))
            except OSError:
                pass
    task_limit = tasks + 64
    resource.setrlimit(resource.RLIMIT_NPROC, (task_limit, task_limit))
    os.closerange(3, 4096)
    # Resolve/load libseccomp before Landlock removes access to loader helpers.
    restrict_syscalls()
    restrict_files(work, packet['runtimes'])
    os.execve(packet['argv'][0], packet['argv'], packet['environment'])


if __name__ == '__main__':
    main()
