#!/usr/bin/env python

import logging
import base64
from twisted.internet import protocol
from twisted.protocols import basic
from twisted.internet import ssl
from OpenSSL import SSL

class ProxyHTTPSConnectionFactory(protocol.ClientFactory):

    def __init__(self, super, host, port, use_ssl = True, proxy_user = None, proxy_pass = None):
        self.super = super
        self.host = host
        self.port = port
        self.proxy_user = proxy_user
        self.proxy_pass = proxy_pass
        self.use_ssl = use_ssl

    def startedConnecting(self, connector):
        self.super.startedConnecting(connector)

    def clientConnectionFailed(self, connector, reason):
        #logging.debug('clientConnectionFailed here %s', reason)
        self.super.clientConnectionFailed(connector, reason)

    def clientConnectionLost(self, connector, reason):
        #logging.debug('clientConnectionLost here %s', reason)
        if self.connection and self.connection.proxy_error:
            self.super.clientConnectionFailed(connector, reason)
        else:
            self.super.clientConnectionLost(connector, reason)

    def buildProtocol(self, addr):
        logging.debug('Connected to proxy, starting connection %s', addr)
        self.connection = HTTPSProxyConnection(addr, self.super, self.host, self.port, self.use_ssl, self.proxy_user, self.proxy_pass)
        return self.connection

class ProxyError:
    def __init(self):
        pass

class HTTPSProxyConnection(basic.LineReceiver):

    def __init__(self, addr, superFactory, host, port, use_ssl = True, proxy_user = None, proxy_pass = None):
        self.addr = addr
        self.superFactory = superFactory
        self.host = host
        self.port = port
        self.proxy_user = proxy_user
        self.proxy_pass = proxy_pass
        self.ok_received = False
        self.super = None
        self.use_ssl = use_ssl
        self.proxy_error = False

    delimeter = '\r\n'

    def connectionMade(self):
        #Send CONNECT here
        logging.debug('Sending necessary headers %s:%s, %s:%s', self.host, self.port, self.proxy_user, self.proxy_pass)
        self.sendLine(str('CONNECT %s:%s HTTP/1.0' % (self.host, self.port)))
        if self.proxy_user and self.proxy_pass:
            self.sendLine('Proxy-Authorization: Basic %s' % base64.encodestring("%s:%s" %(self.proxy_user, self.proxy_pass)))
        self.sendLine('Pragma: no-cache')
        self.sendLine('')

    def rawDataReceived(self, data):
        if self.super:
            #logging.debug('Some data... %i', len(data))
            self.super.dataReceived(data)

    def lineReceived(self, line):
        logging.debug('Received line: %s', line)
        if not self.ok_received and line.startswith('HTTP/1.0 200'):
            self.ok_received = True
            return
        if not line and self.ok_received:
            logging.debug('Ready to initiate new connection')
            self.setRawMode()
            if self.use_ssl:
                self.transport.startTLS(ssl.ClientContextFactory())
            self.super = self.superFactory.buildProtocol(self.addr)
            self.super.transport = self.transport
            self.super.connectionMade()
            return
        logging.error('Proxy response not 200 - report error')
        self.proxy_error = True
        self.transport.loseConnection()


    def connectionLost(self, reason=protocol.connectionDone):
        if self.super:
            self.super.connectionLost(reason)
