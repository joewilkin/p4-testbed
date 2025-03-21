import socket 
import json

s = socket.socket()

port = 12345

s.connect(('10.5.52.9', port))

data = s.recv(1024).decode()

tables = json.loads(data)

print(tables['tables'])

s.close()