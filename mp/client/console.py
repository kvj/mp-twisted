#!/usr/bin/env python

import logging
import cmd
from twisted.internet import reactor, stdio
from twisted.protocols import basic
import sys
from mp import message, common
from mp.client.termcolor import colored
import datetime
import time

server = 1

class Cmd(basic.LineReceiver):

	defaultPlugin = None
	multiLine = False

	from os import linesep as delimiter
	def lineReceived(self, line):
		#logging.debug('Parsing %s', line)
		if line == 'quit':
			#Try to stop reactor
			logging.debug('Stopping client')
			try:
				reactor.stop()
			except Exception, err:
				pass
			return
		is_num = 0
		try:
			is_num = int(line)
		except:
			pass
		if is_num>0:
			line = u'reply to %s' % line
		#Just command - split and send
		arr = line.split()
		if len(arr) == 0:
			if self.multiLine:
				#Send message here
				try:
					self.message.set(self.valueField, u'\n'.join(self.value))
					send_message(self.connection, self.message)
				except Exception, err:
					logging.exception('Error sending message: %s', err)
			self.multiLine = False
			return False
		if self.multiLine:
			#Save line
			self.value.append(line)
			return True

		m = message.Message(arr[0])

		if m.name in ['def', 'default']:
			if len(arr)>1:
				self.defaultPlugin = arr[1]
			else:
				self.defaultPlugin = None
			return False
		#if len(arr)>=3 and arr[0] == 'users':
		#	arr = line.split(None, 2)

		#Name shortcuts
		if m.name in ['pl']:
			m.name = 'plugins'
		if m.name in ['m']:
			m.name = 'message'
		if m.name in ['st']:
			m.name = 'status'
		if m.name in ['u']:
			m.name = 'user'
		if m.name in ['uuu']:
			m.name = 'users'
		if m.name in ['g']:
			m.name = 'group'
		if m.name in ['gg']:
			m.name = 'groups'
		if m.name in ['ug']:
			m.name = 'unread_groups'
		if m.name in ['uu']:
			m.name = 'unread_users'
		if m.name in ['um']:
			m.name = 'unread_messages'
		if m.name in ['r']:
			m.name = 'mark_read'
		if m.name in ['un']:
			m.name = 'unread_networks'


		if len(arr) >= 4 and arr[0] == 'net' and arr[1] == 'opt':
			#net opt <net> <opt>
			m.set(arr[1], arr[2])
			arr = line.split(None, 4)
			m.set('name', arr[3])
			if len(arr)>4:
				m.set('value', arr[4])
			else:
				m.set('value', None)
			send_message(self.connection, m)
			return
		new_arr = []
		brace_found = False
		value = None
		for word in arr:
			if brace_found:
				if word.endswith('"'):
					value += ' '+word[:-1]
					new_arr.append(value)
					brace_found = False
				else:
					value += ' '+word
			else:
				if word.startswith('"') and not word.endswith('"'):
					value = word[1:]
					brace_found = True
				else:
					new_arr.append(word)
		if brace_found:
			new_arr.append(value)
		for i in range((len(new_arr)-1)/2):
			m.set(new_arr[2*i+1], new_arr[2*i+2])

		if not m.get('via') and self.defaultPlugin:
			m.set('via', self.defaultPlugin)
		#logging.debug('Message is ready...')
		if m.name in ['message', 'reply']:
			self.multiLine = True
			self.message = m
			self.valueField = 'message'
			self.value = []
			print_line('End message with empty line')
			return True

		try:
			send_message(self.connection, m)
		except Exception, err:
			logging.exception('Error sending message: %s', err)

interface = Cmd()

def send_message(server, message):
	if server:
		server.send_message(message)
	else:
		logging.error('No connection is active')

def print_line(line, color = None):
	try:
		print colored(line.encode('utf-8'), color)
	except Exception, err:
		logging.exception('Error while printing %s: %s', line, err)

def gmt_iso_to_str(iso):
	delta = datetime.timedelta()
	try:
		if common.config.has_option('Client', 'tz'):
			delta = datetime.timedelta(hours = common.config.getfloat('Client', 'tz'))
	except:
		pass
	current = datetime.datetime.fromtimestamp(time.mktime(time.gmtime()))
	current = current + delta
	parsed = current

	try:
		p = datetime.datetime.strptime(iso, '%Y-%m-%dT%H:%M:%S')
		parsed = p + delta
	except Exception, err:
		logging.exception('Error while converting %s to string: %s', iso, err)
	format = '%I:%M %p'
	try:
		show_year = False
		if current.year!=parsed.year:
			show_year = True
		show_date = False
		if current.month!=parsed.month or current.day!=parsed.day or show_year:
			show_date = True
		show_seconds = False
		if not show_date and current.hour==parsed.hour and current.minute==parsed.minute:
			show_seconds = True
		if show_seconds:
			format = '%I:%M:%S %p'
		if show_date and not show_year:
			format = '%m/%d %I:%M %p'
		if show_year:
			format = '%y, %m/%d %I:%M %p'
	except Exception, err:
		pass
	return parsed.strftime(format)

def print_message(m, _from = ''):
	status = ''
	if m.get('status'):
		status = '[%s]' % m.get('status')
	_sender = m.get('user', m.get('userid', ''))
	_from = m.get('via', _from)
	if _from:
		_from = '[%s]' % _from
	if _sender:
		_sender = ' %s%s' % (status, _sender)
	_id = m.get('messageid')
	_date = gmt_iso_to_str(m.get('message-date'))
	if _id:
		_id = ' #%s ' % _id
	print_line('%s%s%s%s: %s' % (_from, _id, _date, _sender, m.get('message')), 'green')

def process_message(message, connection):
	#logging.debug('Message %s from %s', message.name, message.get('from'))
	if 'plugins' == message.name:
		print_line('Available plugins:')
		for key in message.keys():
			print_line('%10s: %s' % (key, message.get(key, 'No description')))

	if 'networks' == message.name:
		print_line('Active networks:')
		for net in message.get('networks', []):
			arr = []
			arr.append(net.get('type'))
			for key in net.keys():
				if key not in ['type', 'name']:
					arr.append('%s: %s' % (key, net.get(key)))
			print_line('%10s: %s' % (net.get('name'), u', '.join(arr)))

	if 'unread_networks' == message.name:
		print_line('Unread networks:')
		for net in message.get('networks', []):
			print_line('%10s: %s' % (net.get('name'), net.get('count')))

	if 'options' == message.name:
		print_line('Plugin options:')
		for key in message.keys():
			print_line('%10s: %s' % (key, message.get(key, '')))

	def print_user(entry):
		status = ''
		if entry.get('status'):
			status = '[%s]' % entry.get('status')
		net = ''
		if entry.get('net'):
			net = '[%s]' % entry.get('net')
		status_str = ''
		if entry.get('status-string'):
			status_str = '/%s' % entry.get('status-string')
		count = ''
		if entry.get('count'):
			count = '[%s]' % entry.get('count')
		print_line('%15s: %s%s%s%s%s' % (entry.get('userid', ''), count, net, status, entry.get('user', ''), status_str))

	_from  = ''
	if message.get('net'):
		_from = '[%s]' % (message.get('net'))

	def user_compare(u1, u2):
		s1 = u1.get('status', None)
		s2 = u2.get('status', None)
		n1 = u1.get('user', u1.get('group', ''))
		n2 = u2.get('user', u2.get('group', ''))
		#logging.debug('Compare %s and %s %s %s', n1, n2, s1, s2)
		if s1 == s2:
			if n1>n2:
				return 1
			elif n1<n2:
				return -1
			else:
				return 0
		if not s1:
			return -1
		if not s2:
			return 1
		if s1 == 'online':
			return -1
		if s2 == 'online':
			return 1
		if s1 == 'offline':
			return 1
		if s2 == 'offline':
			return -1
		if s1>s2:
			return 1
		elif s1<s2:
			return -1
		else:
			return 0
	def sort_messages(m1, m2):
		d1 = m1.get('message-date', '')
		d2 = m2.get('message-date', '')
		if d1>d2:
			return -1
		elif d1<d2:
			return 1
		else:
			return 0
	def sort_by_count(i1, i2):
		c1 = i1.get('count', 0)
		c2 = i2.get('count', 0)
		if c1>c2:
			return -1
		elif c1<c2:
			return 1
		return 0

	if 'users' == message.name:
		print_line('%sUsers:' % (_from))
		for user in sorted(message.get('users', []), user_compare):
			print_user(user)

	if 'unread_users' == message.name:
		print_line('%sUnread users:' % (_from))
		for user in sorted(message.get('users', []), sort_by_count):
			print_user(user)

	if 'groups' == message.name:
		print_line(u'%sGroups:' % (_from))
		for group in message.get('groups', []):
			print_line('%10s: %s' % (group.get('groupid', 'None'), group.get('group', '')))

	if 'unread_groups' == message.name:
		print_line(u'%sUnread groups:' % _from)
		for group in sorted(message.get('groups', []), sort_by_count):
			print_line('%10s: [%s]%s' % (group.get('groupid', 'None'), group.get('count', 0), group.get('group', '')))

	if 'unread_messages' == message.name:
		print_line(u'%sUnread messages:' % _from)
		for mess in sorted(message.get('messages', []), sort_messages):
			print_message(mess, message.get('net', ''))

	if 'mark_read' == message.name:
		print_line(u'%sMarked messages as read: %i' % (_from, len(message.get('messages', []))))

	if 'group' == message.name:
		print_line('%sGroup details:' % (_from))
		for ent in sorted(message.get('entries', []), user_compare):
			if ent.get('user'):
				print_user(ent)
			else:
				print_line('%s: [%s]' % (ent.get('net', ''), ent.get('group', '')))

	if 'user' == message.name:
		print_line('%sUser details:' % (_from))
		for ent in sorted(message.get('entries', []), user_compare):
			print_line('%s: %s' % (ent.get('net', ''), ent.get('user', '')))

	if 'error' == message.name:
		print_line('%sError: %s' % (_from, message.get('text', 'No error description')), 'red')

	if 'progress' == message.name:
		print_line('%sProgress: %s' % (_from, message.get('text', 'No message')), 'yellow')

	if 'ok' == message.name:
		print_line('%sComplete: %s' % (_from, message.get('text', '')))

	if 'message' == message.name:
		print_message(message, message.get('net', ''))

def client_connected(connection):
	logging.debug('Connection established, show prompt')
	interface.connection = connection
	print_line('Type command:')
	stdio.StandardIO(interface)

def client_disconnected(connection):
	logging.debug('Connection broken, goodbye')
	try:
		reactor.stop()
	except Exception, err:
		pass
