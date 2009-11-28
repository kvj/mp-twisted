#!/usr/bin/env python

from twisted.internet import reactor
from twisted.web import client
import base64
import logging
from twisted.internet import ssl
from mp.network import https

proxy_host = None
proxy_port = None
proxy_user = None
proxy_pass = None

class ProxyHTTPClientFactory(client.HTTPClientFactory):

	def __init__(self, uri, proxy_host, proxy_port, *args, **kwargs):
		self.proxy_host = proxy_host
		self.proxy_port = proxy_port
		client.HTTPClientFactory.__init__(self, uri, *args, **kwargs)

	def buildProtocol(self, addr):
		logging.info('Connected')
		return client.HTTPClientFactory.buildProtocol(self, addr)

	def setURL(self, url):
		#logging.debug('Setting URL: %s', url)
		prev_host = getattr(self, 'host', None)
		client.HTTPClientFactory.setURL(self, url)
		#logging.debug('After parse: %s %s %s %s', self.scheme, self.host, self.port, self.path)
		self.path = url
		if prev_host!=self.host:
			self.headers['Host'] = self.host
		self.host = self.proxy_host
		self.port = self.proxy_port

def proxifyFactory(factory, host, port, use_ssl = False):
	if not proxy_host or not proxy_port:
		logging.debug('No proxy information - default behaviour')
		if use_ssl:
			reactor.connectSSL(host, port, factory, ssl.ClientContextFactory())
		else:
			reactor.connectTCP(host, port, factory)
		return
	https_factory = https.ProxyHTTPSConnectionFactory(factory, host, port, use_ssl, proxy_user, proxy_pass)
	reactor.connectTCP(proxy_host, proxy_port, https_factory)

def getPage(url, *args, **kwargs):
	if not proxy_host or not proxy_port:
		logging.debug('No proxy information - default behaviour')
		return client.getPage(url, *args, **kwargs)
	scheme, host, port, path = client._parse(url)
	if scheme == 'https':
		logging.debug('Proxy and HTTPS - connect via new class')
		http_factory = client.HTTPClientFactory(url, followRedirect = 0, *args, **kwargs)
		https_factory = https.ProxyHTTPSConnectionFactory(http_factory, host, port, True, proxy_user, proxy_pass)
		reactor.connectTCP(proxy_host, proxy_port, https_factory)
		return http_factory.deferred

	if 'headers' in kwargs:
		headers = kwargs['headers']
	else:
		headers = {}
	if proxy_user and proxy_pass:
		auth = base64.encodestring("%s:%s" %(proxy_user, proxy_pass))
		headers['Proxy-Authorization'] = 'Basic %s' % (auth.strip())
		logging.debug('Adding header: %s', headers['Proxy-Authorization'])
		kwargs['headers'] = headers
	#Cleanup proxy params
	factory = ProxyHTTPClientFactory(url, proxy_host, proxy_port, followRedirect = 0, *args, **kwargs)
	logging.debug('Do proxy %s %i', proxy_host, proxy_port)
	reactor.connectTCP(proxy_host, proxy_port, factory)
	return factory.deferred
