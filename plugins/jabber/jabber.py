#!/usr/bin/env python

import logging
from mp.network import http
from mp.server import plugin, database
from mp import message
import random
from twisted.words.protocols.jabber import client, jid
from twisted.internet import reactor
from twisted.words.xish.xmlstream import STREAM_CONNECTED_EVENT, STREAM_END_EVENT, STREAM_ERROR_EVENT
from twisted.words.protocols.jabber.xmlstream import IQ, STREAM_AUTHD_EVENT, INIT_FAILED_EVENT
from twisted.words.xish.domish import Element
from twisted.internet.task import LoopingCall
import time
import xmpp

ROSTER_NS = 'jabber:iq:roster'

class RosterItem:

	def __init__(self, jid, nickname = None, subscription = 'both', groups = []):
		self.jid = jid.lower()
		self.nickname = nickname
		self.subscription = subscription
		self.groups = groups

	def caption(self):
		if self.nickname:
			return self.nickname
		return self.jid

class PresenceInfo:
	def __init__(self, jid, show = None, priority = 0, status = None):
		self.jid = jid
		self.show = show
		self.priority = priority
		self.status = status

class JabberPlugin(plugin.Plugin):

	PING_INTERVAL = 60

	def _stop_connecting(self):
		self.factory.stopTrying()
		if self.connected:
			try:
				self.stream.transport.loseConnection()
			except:
				pass
		self.factory = None
		self.connected = False


	def send_presence(self, show = None, priority = 0, status = None):
		if not self.connected:
			return False
		pr = Element((self.stream.namespace, 'presence'))
		pr['from'] = self.stream.authenticator.jid.full()
		stop_connection = False
		if show in ['offline', 'unavailable']:
			pr['type'] = 'unavailable'
			stop_connection = True
		else:
			if show:
				pr.addElement((self.stream.namespace, 'show'), content = show)
			if status:
				pr.addElement((self.stream.namespace, 'status'), content = status)
		pr.addElement((self.stream.namespace, 'priority'), content = str(priority))
		self.stream.send(pr)
		if stop_connection:
			self._stop_connecting()

	def _connected(self, stream):
		logging.debug('XMPP stream connected')

	def _presence(self, element):
		_from = element.getAttribute('from', None)
		if not _from:
			return
		if element.getAttribute('type', '') == 'subscribe':
			#Subscription request from _from
			logging.info('Got subscription request from %s - auto reply', _from)
			self.add_roster_item(_from.lower(), None, 'subscribed')
		show = None
		if element.getAttribute('type', '') == 'unavailable':
			show = 'unavailable'
		else:
			if element.show:
				show = str(element.show)
		priority = 0
		if element.priority:
			priority = int(str(element.priority))
		status = None
		if element.status:
			status = element.status.__str__()
		_jid = jid.JID(_from)
		userhost = _jid.userhost().lower()
		resource = _jid.resource
		arr = {}
		if userhost in self.presences:
			arr = self.presences[userhost]
		else:
			self.presences[userhost] = arr
		if resource in arr:
			#Update existing resource
			if show == 'unavailable':
				del arr[resource]
			else:
				arr[resource].show = show
				arr[resource].priority = priority
				arr[resource].status = status
		else:
			if show != 'unavailable':
				arr[resource] = PresenceInfo(_from, show, priority, status)
		#logging.debug('Got presence from %s: %s', _from, element.toXml())

	def _iq(self, element):
		#logging.debug('Got iq from %s: %s', element.getAttribute('from', ''), element.toXml())
		if element.query and element.query.uri == ROSTER_NS:
			#Roster management here
			#logging.debug('Roster management %s', element.query.uri)
			for item in element.query.elements():
				_jidtxt = item.getAttribute('jid')
				if not _jidtxt:
					continue
				_jid = jid.JID(_jidtxt)
				userhost = _jid.userhost().lower()
				if item.getAttribute('subscription') == 'remove':
					for id in self.roster:
						if self.roster[id].jid == userhost:
							del self.roster[id]
							break
				else:
					#Add or update
					ri = None
					for id in self.roster:
						if self.roster[id].jid == userhost:
							ri = self.roster[id]
							break
					if ri:
						ri.nickname = item.getAttribute('name')
						ri.subscription = item.getAttribute('subscription', 'none')
					else:
						ri = RosterItem(userhost, item.getAttribute('name'), item.getAttribute('subscription', 'none'))
						ri_id = userhost
						self.roster[ri_id] = ri
						ri.id = ri_id
					ri.groups = []
					for gr in item.elements():
						group = gr.__str__()
						ri.groups.append(group)
						has_group = False
						for id in self.groups:
							if self.groups[id] == group:
								has_group = True
								break
						if not has_group:
							self.groups[group.lower()] = group


	def _message(self, element):
		#logging.debug('Got message from %s: %s', element.getAttribute('from', ''), element.toXml())
		if not element.body or not element.body.__str__():
			logging.error('No message body')
			return
		m = message.Message('message')
		_from = None
		_body = element.body.__str__()
		_jid = None
		_date = time.gmtime()
		_thread = None
		_id = self.new_message_id()
		if element.thread:
			_thread = element.thread.__str__()
		if element.hasAttribute('from'):
			_jid = jid.JID(element['from'])
			_from = _jid.userhost().lower()
			_jid = element['from']
			m.set('userid', _from)
			for id in self.roster:
				item = self.roster[id]
				if item.jid == _from:
					if item.nickname:
						m.set('user', item.nickname)
		m.set('message', _body)
		m.set('messageid', _id)
		_time = time.mktime(_date)
		_strtime = self.time_to_iso(_time)
		m.set('message-date', _strtime)
		self.send_message(m)
		cn, c = self.db.open_cursor()
		try:
			
			c.execute('insert into messages (id_message, sender, jid, thread, date_received, body) values (?, ?, ?, ?, ?, ?)', (_id, _from, _jid, _thread, _time, _body))
			self.db.commit(cn)
			logging.debug('Message saved in DB')
		except Exception, err:
			self.db.rollback(cn)
			logging.exception('Error while saving data to DB %s', err)

	def _do_ping(self):
		if not self.connected:
			return
		try:
			iq = IQ(self.stream, 'get')
			iq.addElement(('urn:xmpp:ping', 'ping'))
			iq.send()
			#logging.debug('Ping sent %s', iq.toXml())
		except Exception, err:
			logging.exception('Ping send failed: %s', err)

	def _authorized(self, stream):
		logging.debug('XMPP stream authorized')
		#Set last status
		self.connected = True
		self.factory_connected = True
		self.stream = stream
		self.presences = {}
		self.roster = {}
		self.groups = {}
		self.ids = []
		self.stream.addObserver('/presence', self._presence)
		self.stream.addObserver('/iq', self._iq)
		self.stream.addObserver('/message', self._message)
		self.send_presence(self.show, self.priority, self.status)
		roster = IQ(self.stream, 'get')
		roster.addElement((ROSTER_NS, 'query'))
		roster.send()
		self.send_progress('XMPP session is started')

	def _auth_failed(self, reason):
		logging.error('XMPP stream auth failed: %s', reason)
		self._stop_connecting()

	def _disconnected(self, reason):
		logging.error('XMPP disconnected')
		self.connected = False

	def _connect_failed(self, reason):
		logging.error('XMPP connect failed')
		if not self.factory_connected:
			self.send_progress('XMPP connection failed, stop connecting')
			self._stop_connecting()
		else:
			self.send_progress('XMPP connection failed, reconnecting')

	def _connect_lost(self, reason):
		logging.error('XMPP connection lost')
		self.send_progress('XMPP connection lost')

	def _show_to_status(self, show):
		if not show:
			return 'online'
		if show == 'unavailable':
			return 'offline'
		return show

	def _get_item_state(self, jidstr):
		_jid = jid.JID(jidstr)
		userhost = _jid.userhost().lower()
		if not userhost in self.presences:
			return ('offline', None, None)
		arr = self.presences[userhost]
		if _jid.resource and _jid.resource in arr:
			#Return asked state
			itm = arr[_jid.resource]
			#logging.debug('for %s status %s', jidstr, self._show_to_status(itm.show))
			return (self._show_to_status(itm.show), itm.status, _jid.resource)
		#Search for biggest presence
		max_presence = -129
		show = 'offline'
		status = None
		resource = None
		for res in arr:
			itm = arr[res]
			#logging.debug('Sheck av resource %s %i', jidstr, itm.priority)
			if itm.priority>max_presence:
				show = self._show_to_status(itm.show)
				#logging.debug('for %s status %s', jidstr, show)
				status = itm.status
				resource = res
				max_presence = itm.priority
		#logging.debug('Return here %s', jidstr)
		return (show, status, resource)

	def _user_to_item(self, item, entry = None):
		if not entry:
			entry = message.Message('entry')
		entry.set('userid', item.id)
		entry.set('user', item.caption())
		entry.set('net', self.name)
		show, status, resource = self._get_item_state(item.jid)
		entry.set('status', show)
		entry.set('status-string', status)
		entry.set('resource', resource)
		return entry

	def add_roster_item(self, userjid, name, type = 'subscribe'):
		iq = IQ(self.stream, 'set')
		query = iq.addElement((ROSTER_NS, 'query'))
		item = query.addElement((ROSTER_NS, 'item'))
		item['jid'] = userjid
		if name:
			item['name'] = name
		pr = Element((self.stream.namespace, 'presence'))
		pr['to'] = userjid
		pr['type'] = type
		send_iq = True
		for id in self.roster:
			item = self.roster[id]
			if item.jid == userjid:
				send_iq = False
				break
		try:
			if send_iq:
				self.stream.send(iq)
			self.stream.send(pr)
		except:
			logging.error('Error sending %s message', type)

	def remove_roster_item(self, userjid):
		iq = IQ(self.stream, 'set')
		query = iq.addElement((ROSTER_NS, 'query'))
		item = query.addElement((ROSTER_NS, 'item'))
		item['jid'] = userjid
		item['subscription'] = 'remove'
		pr = Element((self.stream.namespace, 'presence'))
		pr['to'] = userjid
		pr['type'] = 'unsubscribe'
		try:
			self.stream.send(pr)
			self.stream.send(iq)
		except:
			logging.error('Error sending %s message', type)

	def update_roster_item(self, ri):
		iq = IQ(self.stream, 'set')
		query = iq.addElement((ROSTER_NS, 'query'))
		item = query.addElement((ROSTER_NS, 'item'))
		item['jid'] = ri.jid
		item['name'] = ri.nickname
		for g in ri.groups:
			item.addElement((ROSTER_NS, 'group'), content = g)
		try:
			self.stream.send(iq)
		except:
			logging.error('Error sending %s message', type)

	def _random_str(self, length = 16):
		res = []
		for el in random.sample(range(256), length):
			res.append('%x' % el)
		return ''.join(res)

	def send_xmpp_message(self, jid, text, thread = None):
		logging.debug('Sending message to %s: %s', jid, text)
		m = Element((self.stream.namespace, 'message'))
		m['to'] = jid
		m['type'] = 'chat'
		m['from'] = self.stream.authenticator.jid.full()
		if not thread:
			thread = self._random_str()
		m.addElement((self.stream.namespace, 'thread'), content = thread)
		if text:
			m.addElement((self.stream.namespace, 'body'), content = text)
		try:
			self.stream.send(m)
		except:
			logging.error('Error sending message')


	def new_message(self, m, connection):
		#logging.debug('New message in jabber: %s', m.name)
		if m.name in ['status']:
			self.show = m.get('as')
			if m.get('priority'):
				self.priority = int(m.get('priority'))
			if m.get('status'):
				self.status = m.get('status')
			if self.connected:
				self.send_presence(self.show, self.priority, self.status)
			else:
				self.init_factory()
			return

		def unread_counts():
			cn, c = self.db.open_cursor()
			arr = {}
			try:
				c.execute('select sender, count(*) from messages where unread=1 group by sender')
				for row in c:
					arr[row[0]] = row[1]
				self.db.commit(cn)
			except Exception, err:
				self.db.rollback(cn)
				logging.exception('Error while checking group counters: %s', err)
			return arr

		if m.name in ['unread_groups']:
			resp = message.response_message(m, 'unread_groups')
			groups = []
			arr = unread_counts()
			for id in self.groups:
				group = self.groups[id]
				count = 0
				for uid in self.roster:
					item = self.roster[uid]
					if group in item.groups and item.jid in arr:
						count = count + arr[item.jid]
				if count>0:
					gr = message.Message('group')
					gr.set('groupid', id)
					gr.set('group', group)
					gr.set('count', count)
					groups.append(gr)
			resp.set('groups', groups)
			self.send_back(resp, connection)

		if m.name in ['unread_users']:
			resp = message.response_message(m, 'unread_users')
			users = []
			arr = unread_counts()
			for uid in self.roster:
				item = self.roster[uid]
				if item.jid in arr:
					u = message.Message('user')
					self._user_to_item(item, u)
					u.set('count', arr[item.jid])
					users.append(u)
			resp.set('users', users)
			self.send_back(resp, connection)

		if m.name in ['unread_messages']:
			resp = message.response_message(m, 'unread_messages')
			cn, c = self.db.open_cursor()
			user = None
			group = None
			if m.get('user'):
				user = self.get_list_item(self.roster, m.get('user'))
			if m.get('group'):
				group = self.get_list_item(self.groups, m.get('group'))
			id = m.get('id')
			arr = []
			try:
				c.execute('select id_message, sender, body, date_received from messages where unread=1 order by date_received desc')
				for row in c:
					if id and row[0]!=id:
						continue
					if user and row[1] != user.jid:
						continue
					ri = self.get_list_item(self.roster, row[1])
					if group:
						if not ri or group not in ri.groups:
							continue
					#Pack message
					mess = message.Message('message')
					mess.set('messageid', row[0])
					mess.set('message', row[2])
					_time = row[3]
					_strtime = self.time_to_iso(_time)
					mess.set('message-date', _strtime)
					if ri:
						self._user_to_item(ri, mess)
					arr.append(mess)
				self.db.commit(cn)
				resp.set('messages', arr)
				self.send_back(resp, connection)
			except Exception, err:
				self.db.rollback(cn)
				logging.exception('Error listing unread messages: %s', err)
				self.send_error('Error listing unread messages', m, connection)

		if m.name in ['mark_read']:
			resp = message.response_message(m, 'mark_read')
			cn, c = self.db.open_cursor()
			user = None
			group = None
			if m.get('user'):
				user = self.get_list_item(self.roster, m.get('user'))
			if m.get('group'):
				group = self.get_list_item(self.groups, m.get('group'))
			id = m.get('id')
			arr = []
			try:
				c2 = self.db.add_cursor(cn)
				c.execute('select id_message, sender, body, date_received from messages where unread=1')
				for row in c:
					if id and row[0]!=id:
						continue
					if user and row[1] != user.jid:
						continue
					ri = self.get_list_item(self.roster, row[1])
					if group:
						if not ri or group not in ri.groups:
							continue
					#Mark as read
					c2.execute('update messages set unread=0 where id_message=?', (row[0], ))
					#Pack message
					mess = message.Message('message')
					mess.set('messageid', row[0])
					arr.append(mess)
				self.db.commit(cn)
				resp.set('messages', arr)
				self.send_back(resp, connection)
			except Exception, err:
				self.db.rollback(cn)
				logging.exception('Error marking read messages: %s', err)
				self.send_error('Error marking read messages', m, connection)

		if not self.connected:
			self.send_error('Not connected', m, connection)
			return
		if m.name in ['message']:
			#Send new message
			if not m.get('to'):
				self.send_error('No broadcast messages for XMPP', m, connection)
				return
			userjid = m.get('to')
			item = self.get_list_item(self.roster, userjid)
			if item:
				userjid = item.jid
			else:
				self.send_progress('Sending message to unknown user %s' % userjid)
			self.send_xmpp_message(userjid, m.get('message'))
			return

		if m.name in ['groups']:
			resp = message.response_message(m, 'groups')
			#Enumerate all groups
			gr = []
			for id in self.roster:
				item = self.roster[id]
				#logging.debug('roster %s, %s', id, item)
				#logging.debug('Groups %s, %s', item.jid, item.groups)
				for g in item.groups:
					gr.append(g)
			groups = set(gr)
			arr = []
			for id in sorted(self.groups.keys()):
				#logging.debug('Groups#3 %s = %s', id, self.groups[id])
				group = message.Message('group')
				group.set('groupid', id)
				group.set('group', self.groups[id])
				arr.append(group)
			resp.set('groups', arr)
			self.send_back(resp, connection)

		if m.name in ['users']:
			#Prepare all users without groups
			resp = message.response_message(m, 'users')
			if m.get('add'):
				#Add user
				userjid = m.get('add').lower()
				#logging.debug('Add new roster item %s', userjid)
				name = m.get('name')
				#Add user
				self.add_roster_item(userjid, name)
				self.send_ok('User added', m, connection)
				return
			if m.get('del'):
				userid = m.get('del').lower()
				item = self.get_list_item(self.roster, userid)
				if item:
					#Do remove
					self.remove_roster_item(item.jid)
					self.send_ok('User removed', m, connection)
				else:
					self.send_error('Can\'t find user specified', m, conn)
				return
			if m.get('mv'):
				name = m.get('name', '')
				userid = m.get('mv').lower()
				item = self.get_list_item(self.roster, userid)
				if item:
					#Do remove
					item.nickname = name
					self.update_roster_item(item)
					self.send_ok('User updated', m, connection)
				else:
					self.send_error('Can\'t find user specified', m, conn)
				return



			users = []
			for id in self.roster:
				item = self.roster[id]
				#if len(item.groups)>0:
				#	continue
				users.append(self._user_to_item(item))
			resp.set('users', users)
			self.send_back(resp, connection)

		if m.name in ['group']:
			resp = message.response_message(m, 'group')
			if m.get('add'):
				group = m.get('add')
				userid = m.get('user')
				if group not in self.groups:
					self.send_error('Invalid group', m, connection)
					return
				group_name = self.groups[group]
				item = self.get_list_item(self.roster, userid)
				if item:
					#Add group
					if not group_name in item.groups:
						item.groups.append(group_name)
					self.update_roster_item(item)
					self.send_ok('User added', m, connection)
				else:
					self.send_error('Invalid user', m, connection)
				return
			if m.get('del'):
				group = m.get('del')
				userid = m.get('user')
				if group not in self.groups:
					self.send_error('Invalid group', m, connection)
					return
				group_name = self.groups[group]
				item = self.get_list_item(self.roster, userid)
				if item:
					#Add group
					if group_name in item.groups:
						item.groups.remove(group_name)
					self.update_roster_item(item)
					self.send_ok('User removed from group', m, connection)
				else:
					self.send_error('Invalid user', m, connection)
				return
			id = m.get('show')
			arr = []
			group = self.get_list_item(self.groups, id)
			if group:
				#Enumerate all users
				for id in self.roster:
					item = self.roster[id]
					#logging.debug('user %s %s %s', item.jid, item.groups, group)
					if group in item.groups:
						arr.append(self._user_to_item(item))
				resp.set('entries', arr)
				self.send_back(resp, connection)
			else:
				self.send_error('Invalid group', m)


	def init_factory(self):
		if not 'jid' in self.settings:
			self.send_error('No jid settings defined for plugin')
			return
		try:
			self.connected = False
			self.factory_connected = False
			self.jid = jid.JID(self.settings['jid'])
			self.password = self.get_setting('password', '')
			self.host = self.get_setting('host', self.jid.host)
			self.port = self.get_intsetting('port', 5222)
			self.priority = self.get_intsetting('priority', 0)
			self.status = None
			self.show = None

			self.factory = xmpp.XMPPClientFactory(self.jid, self.password)
			self.factory.addBootstrap(STREAM_CONNECTED_EVENT, self._connected)
			self.factory.addBootstrap(STREAM_AUTHD_EVENT, self._authorized)
			self.factory.addBootstrap(INIT_FAILED_EVENT, self._auth_failed)
			self.factory.addBootstrap(STREAM_END_EVENT, self._disconnected)
			self.factory.addObserver(xmpp.STREAM_CONNECTION_FAILED, self._connect_failed)
			self.factory.addObserver(xmpp.STREAM_CONNECTION_LOST, self._connect_lost)

			#Start connecting

			#Try to connect over proxy
			http.proxifyFactory(self.factory, self.host, self.port, self.get_boolsetting('ssl', False))
			#reactor.connectTCP(self.host, self.port, self.factory)
			logging.debug('Connect started')
		except Exception, err:
			logging.exception('Error while creating XMPP connection: %s', err)
			self.send_error('Error while connecting to XMPP server')

	def activate(self):
		self.connected = False
		logging.debug('Jabber is active %s %s', self.name, self.settings)

		#Init database
		try:
			messages = database.Table('messages')
			messages.add_id('id')
			messages.add_column('id_message')
			messages.add_column('sender')
			messages.add_column('jid')
			messages.add_column('thread')
			messages.add_column('date_received')
			messages.add_column('unread', 'INTEGER', default = 1)
			messages.add_column('body')
			self.db.add_table(messages)
			if not self.db.verify_schema():
				return False
		except Exception, err:
			logging.exception('Error while verifying schema: %s', err)
			return False

		self.ping_task = LoopingCall(self._do_ping)
		self.ping_task.start(self.PING_INTERVAL)
		#Create XMPP factory, read settings, start connection
		#self.init_factory()

		#def on_page(page = None):
		#	logging.debug('Page: %s', len(page))
		#
		#def on_error(err = None):
		#	logging.debug('Error: %s', err)
		#
		#defer = http.getPage('https://wave.google.com')
		#defer.addCallback(on_page)
		#defer.addErrback(on_error)
		self.init_factory()
		return True

	def deactivate(self):
		logging.debug('Jabber %s is stopped', self.name)
		self.ping_task.stop()

def get_name():
	return 'jabber'

def get_description():
	return 'Jabber plugin'

def get_class():
	return JabberPlugin
