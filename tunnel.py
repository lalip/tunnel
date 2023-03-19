import socket
from select import select
from time import strftime
from traceback import format_exc
from sys import argv
from ipaddress import ip_address

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
        except Exception as e:
            e.args += (s1.getsockname(),)
            try:
                s1.shutdown(socket.SHUT_RDWR)
                s1.close()
            except:
                pass
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

socks = []
for addr_pair in argv[1:]:
    pieces = addr_pair.split(':')
    if '' in pieces:
        log('IPv6 is not supported yet')
        exit()
    if len(pieces) < 2 or len(pieces) > 4:
        log('Invalid format:', addr_pair)
        exit()

    port = pieces.pop(-1)
    try:
        port = int(port)
        if port < 1 or port > 65535:
            raise ValueError  # reuse except clause
    except ValueError:
        log('Invalid port number:', port)
        exit()

    host = pieces.pop(-1)
    try:
        host = ip_address(host)
    except ValueError:
        log('Invalid address:', host)
        exit()
    if host.version == 6:
        log('IPv6 is not supported yet')
        exit()
    host = str(host)

    remote_addr = host, port

    if pieces:
        # FIXME: DRY!
        port = pieces.pop(-1)
        try:
            port = int(port)
            if port < 1 or port > 65535:
                raise ValueError  # reuse except clause
        except ValueError:
            log('Invalid port number:', port)
            exit()
    else:
        port = 0

    if pieces:
        # FIXME: DRY! again...
        host = pieces.pop(-1)
        try:
            host = ip_address(host)
        except ValueError:
            log('Invalid address:', host)
            exit()
        if host.version == 6:
            log('IPv6 is not supported yet')
            exit()
        host = str(host)
    else:
        host = '0.0.0.0'

    local_addr = host, port

    p = Port(local_addr, remote_addr)
    socks.append(p)
    log('Routing {}:{} -> {}:{}'.format(*p.local_addr, *p.remote_addr))

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
                local_addr = e.args[-1]
                log('Failed to open tunnel: {}:{} -> {}:{}\n{}'.format(
                    *local_addr, *s.remote_addr, e))
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
