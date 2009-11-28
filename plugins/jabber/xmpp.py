#!/usr/bin/env python

from twisted.words.xish import xmlstream
from twisted.words.xish import utility
from twisted.words.protocols.jabber.xmlstream import XmlStream, XmlStreamFactory
from twisted.words.protocols.jabber.client import XMPPAuthenticator
import logging

STREAM_CONNECTION_FAILED = intern("//event/stream/connectfailed")
STREAM_CONNECTION_LOST = intern("//event/stream/connectlost")

class XMPPExtendedStreamFactory(XmlStreamFactory, utility.EventDispatcher):

	def __init__(self, auth):
		XmlStreamFactory.__init__(self, auth)
		utility.EventDispatcher.__init__(self)

	def clientConnectionFailed(self, connector, reason):
		self.dispatch(reason, STREAM_CONNECTION_FAILED)
		XmlStreamFactory.clientConnectionFailed(self, connector, reason)

	def clientConnectionLost(self, connector, reason):
		self.dispatch(reason, STREAM_CONNECTION_LOST)
		XmlStreamFactory.clientConnectionLost(self, connector, reason)


def XMPPClientFactory(jid, password):
	a = XMPPAuthenticator(jid, password)
	return XMPPExtendedStreamFactory(a)
