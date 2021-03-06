# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from twisted.internet.protocol import Protocol
from twisted.internet.protocol import Factory
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor

from calvin.utilities.calvinlogger import get_logger
_log = get_logger(__name__)


class RawDataProtocol(Protocol):
    """A Calvin Server object"""
    def __init__(self, factory, max_length, actor_id):
        self.MAX_LENGTH          = max_length
        self.data_available      = False
        self.connection_lost     = False
        self.factory             = factory
        self._data_buffer        = []
        self._actor_id = actor_id

    def connectionMade(self):
        self.factory.connections.append(self)
        self.factory.trigger()

    def connectionLost(self, reason):
        self.connection_lost = True
        self.factory.connections.remove(self)
        self.factory.trigger()

    def dataReceived(self, data):
        self.data_available = True
        while len(data) > 0:
            self._data_buffer.append(data[:self.MAX_LENGTH])
            data = data[self.MAX_LENGTH:]
        self.factory.trigger()

    def send(self, data):
        self.transport.write(data)

    def close(self):
        self.transport.loseConnection()

    def data_get(self):
        if self._data_buffer:
            data = self._data_buffer.pop(0)
            if not self._data_buffer:
                self.data_available = False
            return data
        else:
            raise Exception("Connection error: no data available")


class LineProtocol(LineReceiver):
    def __init__(self, factory, delimiter, actor_id):
        self.delimiter           = delimiter
        self.data_available      = False
        self.connection_lost     = False
        self._line_buffer             = []
        self.factory             = factory
        self._actor_id = actor_id

    def connectionMade(self):
        self.factory.connections.append(self)
        self.factory.trigger()

    def connectionLost(self, reason):
        self.connection_lost = True
        self.factory.connections.remove(self)
        self.factory.trigger()

    def lineReceived(self, line):
        self.data_available = True
        self._line_buffer.append(line)
        self.factory.trigger()

    def send(self, data):
        LineReceiver.sendLine(self, data)  # LineReceiver is an old style class.

    def close(self):
        self.transport.loseConnection()

    def data_get(self):
        self.line_length_exeeded = False
        if self._line_buffer:
            data = self._line_buffer.pop(0)
            if not self._line_buffer:
                self.data_available = False
            return data
        else:
            raise Exception("Connection error: no data available")


class ServerProtocolFactory(Factory):
    def __init__(self, trigger, mode='line', delimiter='\r\n', max_length=8192, actor_id=None):
        self._trigger             = trigger
        self.mode                = mode
        self.delimiter           = delimiter
        self.MAX_LENGTH          = max_length
        self.connections         = []
        self.pending_connections = []
        self._port               = None
        self._actor_id           = actor_id

    def trigger(self):
        self._trigger(actor_ids=[self._actor_id])

    def buildProtocol(self, addr):
        if self.mode == 'line':
            connection = LineProtocol(self, self.delimiter, actor_id=self._actor_id)
        elif self.mode == 'raw':
            connection = RawDataProtocol(self, self.MAX_LENGTH, actor_id=self._actor_id)
        else:
            raise Exception("ServerProtocolFactory: Protocol not supported")
        self.pending_connections.append((addr, connection))
        return connection

    def start(self, host, port):
        self._port = reactor.listenTCP(port, self, interface=host)

    def stop(self):
        self._port.stopListening()
        for c in self.connections:
            c.transport.loseConnection()

    def accept(self):
        addr, conn = self.pending_connections.pop()
        if not self.pending_connections:
            self.connection_pending = False
        return addr, conn
