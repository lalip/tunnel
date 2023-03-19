import socket
from select import select
from time import strftime
from traceback import format_exc

LOCAL_HOST = '0.0.0.0'
REMOTE_HOST = '172.12.0.2'

LOCAL_PORT = 8000
REMOTE_PORT = 8000

STATUS_OK = 0
STATUS_SHUTDOWN = -1

def log(*args):
    print(strftime('[%Y-%m-%d %H:%M:%S]'), *args)

class Port():
    def __init__(self, local_addr, remote_addr):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(local_addr)
        self.sock.listen()
        self.local_addr = self.sock.getsockname()
        self.remote_addr = remote_addr
        self.buffer = None

    def fileno(self):
        return self.sock.fileno()

    def accept(self):
        s1, _ = self.sock.accept()
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # FIXME: might block for too long?
            s2.connect(self.remote_addr)
        except:
            try:
                s1.close()
            finally:
                raise

        local_sock = Tunnel(s1, 'local', s1.getsockname())
        remote_sock = Tunnel(s2, 'remote', self.remote_addr)
        local_sock.peer = remote_sock
        remote_sock.peer = local_sock
        return [local_sock, remote_sock]

class Tunnel():
    def __init__(self, sock, half, addr):
        self.sock = sock
        self.half = half
        self.addr = addr
        self.buffer = b''
        self.sock.setblocking(0)
        self.done = False

    def fileno(self):
        return self.sock.fileno()

    def tunnel(self):
        try:
            packet = self.sock.recv(4096)
            if not packet:
                raise ConnectionResetError
        except (ConnectionResetError, ConnectionAbortedError):
            return self.peer.shutdown()

        self.peer.buffer += packet
        try:
            return self.peer.resend()
        except BlockingIOError:  # wait for select()
            return STATUS_OK

    def resend(self):
        if not self.buffer:
            return STATUS_OK

        try:
            sent = self.sock.send(self.buffer)
            if sent == 0:
                raise ConnectionResetError
        except (ConnectionResetError, ConnectionAbortedError):
            return self.peer.shutdown()

        self.buffer = self.buffer[sent:]
        return STATUS_OK

    def shutdown(self):
        self.done = True
        errors = 0

        try:
            self.sock.shutdown(socket.SHUT_WR)
        except Exception:
            log(format_exc())
            errors += 1

        if self.peer.done:
            for s in (self.sock, self.peer.sock):
                try:
                    s.close()
                except Exception:
                    log(format_exc())
                    errors += 1

        return errors if errors else STATUS_SHUTDOWN

socks = [Port((LOCAL_HOST, LOCAL_PORT), (REMOTE_HOST, REMOTE_PORT))]

log('Ready!')
while True:
    rlist, wlist, _ = select(socks, filter(lambda s: s.buffer, socks), (), 60)

    for s in wlist:
        try:
            result = s.resend()
        except Exception:
            log('Tunnel failed on', s.sock, '\n' + format_exc())
            socks.remove(s)
            continue

        if result == STATUS_SHUTDOWN:
            socks.remove(s)
            log('Connection shut down successfully',
                '({}:{}, {})'.format(*s.addr, s.half))

        elif result != STATUS_OK:
            socks.remove(s)
            log('Connection shut down with', result, 'errors',
                '({}:{}, {})'.format(*s.addr, s.half))

    for s in rlist:
        if s.buffer is None:  # s is Port, not Tunnel
            try:
                new_socks = s.accept()
            except Exception as e:
                log('Failed to open tunnel: {}:{} -> {}:{}\n{}'.format(
                    *s.local_addr, *s.remote_addr, e))
            else:
                socks += new_socks
                log('Tunnel opened: {}:{} -> {}:{}'.format(
                    *new_socks[0].addr, *s.remote_addr))
            continue

        try:
            result = s.tunnel()
        except Exception:
            log('Tunnel failed on', s.sock, '\n' + format_exc())
            socks.remove(s)
            continue

        if result == STATUS_SHUTDOWN:
            socks.remove(s)
            log('Connection shut down successfully',
                '({}:{}, {})'.format(*s.addr, s.half))

        elif result != STATUS_OK:
            socks.remove(s)
            log('Connection shut down with', result, 'errors',
                '({}:{}, {})'.format(*s.addr, s.half))
