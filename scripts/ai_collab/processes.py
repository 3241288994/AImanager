"""OS process birth identities, not PID-only liveness guesses."""
import ctypes
import functools
from pathlib import Path
import sys


class BsdInfo(ctypes.Structure):
    # macOS SDK sys/proc_info.h: proc_bsdinfo / PROC_PIDTBSDINFO.
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved",
    )] + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)] + [
        (name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid")
    ] + [("nice", ctypes.c_int32), ("start_seconds", ctypes.c_uint64),
         ("start_microseconds", ctypes.c_uint64)]


@functools.lru_cache(maxsize=1)
def darwin_pidinfo():
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    function = library.proc_pidinfo
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    return function


def process_identity(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    try:
        if sys.platform == 'darwin':
            info = BsdInfo()
            size = ctypes.sizeof(info)
            if darwin_pidinfo()(pid, 3, 0, ctypes.byref(info), size) != size:
                return None
            if info.pid != pid or info.status == 5 or not info.start_seconds:
                return None
            return 'darwin:{}:{}'.format(info.start_seconds, info.start_microseconds)
        if sys.platform.startswith('linux'):
            fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
            return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError, AttributeError, OverflowError):
        pass
    return None
