# tunnel.py

A simple script that attempts to "bind" an arbirary address to any interface on your device.

- [Usage](#usage)
- [Why?](#why), or Context
- [Why not?](#why-not), or Alternatives and limitations
- [So, what is this anyway?](#so-what-is-this-anyway), or A quick reimplementation of its core functionality

## Usage

As this is a python script, you'll need a python interpreter installed. Assuming it is invoked as `python`:

- `python tunnel.py 192.168.0.16:3000` will bind a random port (and tell you which one) to `127.0.0.1` on the device. When some client connects to it, the script will open a connection to `192.168.0.16:3000` and proceed to redirect all packets between both connections, such that connecting to the newly bound address is functionally equivalent to connecting directly to the destination.
- `python tunnel.py 5000:192.168.0.16:3000` does the same as above, but now it will attempt to bind port `5000` specifically.
- `python tunnel.py 172.17.0.1:3000:192.168.0.16:3000` will bind to `172.17.0.1` instead, assuming this address is assigned to an interface on the device.
- You can also open multiple tunnels in a single process: say, `python tunnel.py 0.0.0.0:80:127.0.0.1:8000 5000:172.17.0.3:5000`

In its current state, only TCP/IPv4 is supported. Error-checking is not exactly complete, but any wrinkles should be easy to figure out.

This tool is **not meant for use in production! It is duct tape**, and should be treated as such.

## Why?

SSH tunnelling is a very convenient tool for the odd occasion where a service is technically reachable, but you can't connect directly to it for some reason, such as your client using a hardcoded address that won't do, or the service itself telling your browser to connect through localhost (some node-based web development toolchains do this); and also in some setups where your client does not have direct access to the service, but some other device in your network does (ever tried debugging the mobile version of a webapp running inside a docker container within a virtual machine on your desktop, from your phone? you should probably explore a saner setup 😅 but failing that, SSH tunnelling is an easy way to bridge the gap).

This tool aims to serve the same purpose by replacing the SSH server, thus removing this requirement. When it comes to developing quickly, this extra flexibility can be very welcome!

## Why not?

There are plenty of other ways to achieve similar results. Most notably, if the running service is under your control, you should first try binding it to an appropriate interface directly, or at the very least to that device's localhost, where you can later expose it through features already present in your operating system (are you here because of Windows? maybe use `netsh`!). On the other hand, if the service or the network aren't under your control, there's probably a good reason your problem can't be resolved through SSH tunnelling alone. Consider whether usage of this tool can get you or somebody else in trouble 👀

## So, what is this anyway?

The basic idea can be tested in an interactive python interpreter as follows (warning: these snippets are intentionally messy, and I've skipped all the error handling!):

1. Binding to an address on the device:

```python3
import socket

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(('127.0.0.1', 5000))
server.listen()
```

2. Setting up a bit of structure to pair connections together:

We'll create a list `sockets` to hold all the sockets so we can use `select` to wait for packets, and a dict `socket_pairs` so we know what needs to be sent where.

```python3
sockets = [server]
socket_pairs = {}

def establish_tunnel(src_socket):
    dest_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dest_socket.connect(('192.168.1.100', 8080))  # or some other destination

    sockets.append(src_socket)
    sockets.append(dest_socket)

    src_socket_dict = {
        'socket': src_socket,
        'buffer': b'',  # packets waiting to be sent to this socket
    }

    dest_socket_dict = {
        'socket': dest_socket,
        'buffer': b'',
        'peer': src_socket_dict,  # the other end of this connection
    }

    src_socket_dict['peer'] = dest_socket_dict  # yup, circular references

    socket_pairs[src_socket.fileno()] = src_socket_dict
    socket_pairs[dest_socket.fileno()] = dest_socket_dict
```

3. Finally, listen for incoming connections and route each connection's packets to its peer:

```python3
import select

while True:
    writable_sockets = [pair['socket'] for pair in socket_pairs.values() if pair['buffer']]  # every socket waiting to send()
    rlist, wlist, _ = select.select(sockets, writable_sockets, ())

    for sock in rlist:
        if sock == server:
            new_socket, _ = server.accept()
            establish_tunnel(new_socket)

        else:
            packet = sock.recv(4096)  # or some other sensible value
            # don't forget to remove closed connections or it'll spin! skipped for brevity
            socket_pairs[sock.fileno()]['peer']['buffer'] += packet  # prepare the data to be sent to the other end

            # maybe conditionally add the socket's peer to wlist if you'd rather not call select() again

    for sock in wlist:
        packet = socket_pairs[sock.fileno()]['buffer']
        sent = sock.send(packet)
        socket_pairs[sock.fileno()]['buffer'] = packet[sent:]
```

The [full script](tunnel.py) wraps classes around the sockets for clarity and a bit of encapsulation, features basic argument parsing, and outputs some diagnostic logs so you can figure out what's wrong if your tunnels are not working as intended; other than that, its core functionality is as above.
