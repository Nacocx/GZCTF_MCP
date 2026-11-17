"""Internal supervisor: stop wsrx when the owning MCP process closes its lifeline.

A small stdlib-only helper keeps subprocess cleanup working even if the MCP
process is killed before its async lifespan cleanup can run. Not an MCP tool.
"""

import signal
import subprocess
import sys
import threading


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Internal wsrx supervisor requires an executable")
    try:
        child = subprocess.Popen(
            sys.argv[1:],
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=False,
        )
    except OSError:
        raise SystemExit("wsrx could not be started") from None

    def stop(*_):
        if child.poll() is None:
            try:
                child.terminate()
            except ProcessLookupError:
                return
            try:
                child.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
                child.wait()

    def watch_parent():
        # The MCP parent holds this pipe open, without sending any data.
        # EOF also arrives if the parent is forcefully killed.
        try:
            sys.stdin.buffer.read(1)
        finally:
            stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        code = child.wait()
    finally:
        stop()
    raise SystemExit(code if code >= 0 else 1)


if __name__ == "__main__":
    main()
