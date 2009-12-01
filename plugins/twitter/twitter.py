import logging
from mp.network import http
from mp.server import plugin, database
from mp import message
from twisted.internet import reactor
from twisted.words.xish.domish import Element
from twisted.internet.task import LoopingCall
import time
from lib import twitter

class TwitterPlugin(plugin.Plugin):

	UPDATE_INTERVAL = 30

	def _on_users_come(self, arr):
		logging.debug('Users are here: %s', len(arr))
		pass

	def _update_users(self):
		d = self.twitter.friends2()
		d.addCallback(self._on_users_come)
		d.addErrback(self._on_update_err, 'Error fetching users')

	def init_twitter(self):
		tw = twitter.Twitter(self.get_setting('login'), self.get_setting('password'))
		d = tw.verify_credentials()
		def ok(result):
			logging.debug('Complete init_twitter')
			self.twitter = tw
			self._update_tline()
			self._update_users()
		def err(err):
			logging.error('Error %s', err)
			self.send_error('Can\'t connect to twitter')
		d.addCallback(ok)
		d.addErrback(err)

	def _get_last_id(self, name, c):
		c.execute('select last_id from ids where name=?', (name.lower(), ))
		r = c.fetchone()
		if r:
			return r[0]
		return None

	def _set_last_id(self, name, id, c):
		c.execute('delete from ids where name=?', (name.lower(), ))
		c.execute('insert into ids (name, last_id) values (?, ?)', (name.lower(), id))

	def _on_update_err(self, error, msg = None):
		logging.debug('We have error: %s', msg)
		self.send_error(msg)

	def _on_update_ok(self, arr, type = None, id_name = None):
		logging.debug('Update complete %s, %s', type, len(arr))
		if len(arr) == 0:
			return
		cn, c = self.db.open_cursor()
		try:
			id = arr[0].id
			self._set_last_id(id_name, id, c)
			for entry in arr:
				try:
					user = None
					if hasattr(entry, 'sender'):
						user = entry.sender
					else:
						user = entry.user
					_sender = user.screen_name
					_id = entry.id
					_date = time.strptime(entry.created_at, '%a %b %d %H:%M:%S +0000 %Y')
					_time = time.mktime(_date)
					#logging.debug('Entry %s, %s, %s', _id, entry.created_at, entry.in_reply_to_status_id)
					c.execute('select id_message from messages where id_tweet=?', (_id, ))
					r = c.fetchone()
					if not r:
						message_id = self.new_message_id()
						c.execute('insert into messages (id_message, id_tweet, sender, date_received, body, type, in_reply) values (?, ?, ?, ?, ?, ?, ?)', (message_id, _id, _sender, _time, entry.text, type, entry.in_reply_to_status_id))
					else:
						message_id = r[0]
						continue
					m = message.Message('message')
					m.set('messageid', message_id)
					m.set('userid', _sender)
					#m.set('user', user.name)
					m.set('message', entry.text)
					m.set('type', type)
					m.set('message-date', self.time_to_iso(_time))
					self.send_message(m)
				except Exception, err:
					logging.exception('Error on entry')
			self.db.commit(cn)

		except Exception, err:
			self.db.rollback(cn)
			logging.exception('Error while saving timeline')

	def _start_update(self, id, err_msg, method, type = None, id_name = None):
		#logging.debug('_start_update %s = %s', id_name, id)
		params = {'since_id': id}
		d = method(params = params)
		d.addCallback(self._on_update_ok, type = type, id_name = id_name)
		d.addErrback(self._on_update_err, err_msg)


	def _update_tline(self):
		if not self.twitter:
			return
		#logging.debug('Updating tline here:')
		cn, c = self.db.open_cursor()
		try:
			#c.execute('delete from ids')
			id = self._get_last_id('tweet', c)
			repl = self._get_last_id('replies', c)
			direct = self._get_last_id('direct', c)

			self._start_update(id, 'Error updating home timeline', self.twitter.home_timeline, 'normal', 'tweet')
			self._start_update(repl, 'Error updating replies timeline', self.twitter.replies, 'reply', 'replies')
			self._start_update(direct, 'Error updating direct messages timeline', self.twitter.direct_messages, 'direct', 'direct')

			self.db.commit(cn)
		except Exception, err:
			logging.exception('Error while updating timelines: %s', err)
			self.db.rollback(cn)


	def activate(self):
		logging.debug('Twitter is active %s %s', self.name, self.settings)
		self.twitter = None
		#Init database
		try:
			messages = database.Table('messages')
			messages.add_id('id')
			messages.add_column('id_message')
			messages.add_column('id_tweet')
			messages.add_column('sender')
			messages.add_column('date_received')
			messages.add_column('unread', 'INTEGER', default = 1)
			messages.add_column('body')
			messages.add_column('in_reply')
			messages.add_column('type')
			#messages.add_column('retweet_of')
			self.db.add_table(messages)

			ids = database.Table('ids')
			ids.add_id('id')
			ids.add_column('name')
			ids.add_column('last_id', 'INTEGER')
			self.db.add_table(ids)
			if not self.db.verify_schema():
				return False
		except Exception, err:
			logging.exception('Error while verifying schema: %s', err)
			return False
		self.refresh_task = LoopingCall(self._update_tline)
		self.refresh_task.start(self.get_intsetting('update_min', 1) * 60)
		self.init_twitter()
		return True

	def deactivate(self):
		logging.debug('Twitter %s is stopped', self.name)
		self.refresh_task.stop()

	def setting_changed(self, name, value):
		if name in ['login', 'password'] and not self.twitter:
			self.init_twitter()

	def new_message(self, m, connection):
		if m.name in ['unread_messages']:
			resp = message.response_message(m, 'unread_messages')
			cn, c = self.db.open_cursor()
			user = None
			try:
				c.execute('select id_message, sender, body, date_received, type, id_tweet from messages where unread=1 order by date_received')
				arr = []
				for row in c:
					#if id and row[0]!=id:
					#	continue
					#if user and row[1] != user.jid:
					#	continue
					#ri = self.get_list_item(self.roster, row[1])
					#if group:
					#	if not ri or group not in ri.groups:
					#		continue
					#Pack message
					mess = message.Message('message')
					mess.set('messageid', row[0])
					mess.set('userid', row[1])
					mess.set('message', row[2])
					mess.set('type', row[4])
					id_tweet = row[5]
					mess.set('via', self.name)
					_time = row[3]
					_strtime = self.time_to_iso(_time)
					mess.set('message-date', _strtime)
					#logging.debug('tweet %s - %s', id_tweet, _strtime)
					#if ri:
					#	self._user_to_item(ri, mess)
					arr.append(mess)
				self.db.commit(cn)
				resp.set('messages', arr)
				self.send_back(resp, connection)
			except Exception, err:
				self.db.rollback(cn)
				logging.exception('Error listing unread messages: %s', err)
				self.send_error('Error listing unread messages', m, connection)
			return True

		if m.name in ['mark_read']:
			cn, c = self.db.open_cursor()
			user = None
			try:
				c2 = self.db.add_cursor(cn)
				arr = []
				c.execute('select id_message, sender from messages where unread=1')
				for r in c:
					#Just mark as read
					c2.execute('update messages set unread=0 where id_message=?', (r[0], ))
					mess = message.Message('message')
					mess.set('messageid', r[0])
					arr.append(mess)
				self.db.commit(cn)
				resp = message.response_message(m, 'mark_read')
				resp.set('messages', arr)
				self.send_back(resp, connection)
			except Exception, err:
				self.db.rollback(cn)
				logging.exception('Error in mark_read: %s', err)
				self.send_error('Error marking messages as read', m, connection)
			return True

		return False


def get_name():
	return 'twitter'

def get_description():
	return 'Twitter plugin'

def get_class():
	return TwitterPlugin
