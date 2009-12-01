#!/usr/bin/env python
"""
Twisted Twitter interface.

Copyright (c) 2008	Dustin Sallings <dustin@spy.net>
Copyright (c) 2009	Kevin Dunglas <dunglas@gmail.com>
"""

import base64
import urllib
import mimetypes
import mimetools
import logging
from mp.network import http

from lib import oauth, txml

from twisted.internet import defer
from twisted.web import client


SIGNATURE_METHOD = oauth.OAuthSignatureMethod_HMAC_SHA1()

BASE_URL="http://twitter.com"
SEARCH_URL="http://search.twitter.com/search.atom"

class EntryCollect:

	def __init__(self):
		self.entries = []

	def on_entry(self, entry):
		self.entries.append(entry)

	def on_finish(self, data):
		return self.entries

class CursorCollect:

	def on_entry(self, entry):
		#logging.debug('CursorCollect: on_entry %s', entry)
		self.entries.append(entry)

	def on_error(self, error):
		#logging.debug('CursorCollect: on_error: %s', error)
		self.defer.errback(error)

	def on_finish(self, data, factory):
		#logging.debug('CursorCollect: on_finish %s', factory.simple_tags)
		next_cursor = factory.simple_tags['next_cursor']
		if next_cursor not in ['0', '-1']:
			self.params['cursor'] = next_cursor
			self._start()
		else:
			#logging.debug('Stupid complete %s', len(self.entries))
			self.defer.callback(self.entries)

	def _start(self):
		if 'cursor' not in self.params:
			self.params['cursor'] = -1
		d = self.twitter._get(self.url, self.on_entry, self.params, self.feed_type)
		d.addCallback(self.on_finish, d.factory)
		d.addErrback(self.on_error)

	def __init__(self, twitter, url, params = None, feed_type = txml.StatusList):
		self.entries = []
		self.twitter = twitter
		self.params = params or {}
		self.feed_type = feed_type
		self.url = url
		self.defer = defer.Deferred()
		self._start()

class PageCollect(CursorCollect):
	
	def on_entry(self, entry):
		#logging.debug('PageCollect: on_entry %s', entry)
		self.entries.append(entry)

	def on_error(self, error):
		#logging.debug('PageCollect: on_error')
		self.defer.errback(error)

	def on_finish(self, data, factory):
		dif = len(self.entries) - self.prev_count
		#logging.debug('PageCollect: on_finish %s', dif)
		if dif>0 and 'since_id' in self.params and self.params['since_id']:
			self.page = self.page + 1
			self._start()
		else:
			#logging.debug('PageCollect complete %s', len(self.entries))
			self.defer.callback(self.entries)

	def _start(self):
		self.prev_count = len(self.entries)
		if self.page>1:
			self.params['page'] = self.page
		#logging.debug('PageCollect._start page: %s %s %s', self.url, self.page, self.params)
		d = self.twitter._get(self.url, self.on_entry, self.params, self.feed_type)
		d.addCallback(self.on_finish, d.factory)
		d.addErrback(self.on_error)

	def __init__(self, twitter, url, params = None, feed_type = txml.StatusList):
		self.entries = []
		self.twitter = twitter
		self.params = params or {}
		self.feed_type = feed_type
		self.url = url
		self.defer = defer.Deferred()
		self.page = 1
		self._start()
		
class Twitter(object):

	agent="twitty twister"

	def __init__(self, user=None, passwd=None,
		base_url=BASE_URL, search_url=SEARCH_URL,
				 consumer=None, token=None, signature_method=SIGNATURE_METHOD):

		self.base_url = base_url
		self.search_url = search_url

		self.use_auth = False
		self.use_oauth = False

		if user and passwd:
			self.use_auth = True
			self.username = user
			self.password = passwd

		if consumer and token:
			self.use_auth = True
			self.use_oauth = True
			self.consumer = consumer
			self.token = token
			self.signature_method = signature_method


	def __makeOAuthHeader(self, method, url, parameters={}, headers={}):
		oauth_request = oauth.OAuthRequest.from_consumer_and_token(self.consumer,
			token=self.token, http_method=method, http_url=url, parameters=parameters)
		oauth_request.sign_request(self.signature_method, self.consumer, self.token)

		headers = dict(headers.items() + oauth_request.to_header().items())

		return headers

	def _makeAuthHeader(self, headers={}):
		authorization = base64.encodestring('%s:%s'
			% (self.username, self.password))[:-1]
		headers['Authorization'] = "Basic %s" % authorization
		return headers

	def _urlencode(self, h):
		rv = []
		for k,v in h.iteritems():
			if k and v:
				if isinstance(v, int) or isinstance(v, long):
					v = str(v)
				rv.append('%s=%s' % (urllib.quote(k.encode("utf-8")), urllib.quote(v.encode("utf-8"))))
		return '&'.join(rv)

	def __encodeMultipart(self, fields, files):
		"""
		fields is a sequence of (name, value) elements for regular form fields.
		files is a sequence of (name, filename, value) elements for data to be uploaded as files
		Return (content_type, body) ready for httplib.HTTP instance
		"""
		boundary = mimetools.choose_boundary()
		crlf = '\r\n'

		l = []
		for k, v in fields:
			l.append('--' + boundary)
			l.append('Content-Disposition: form-data; name="%s"' % k)
			l.append('')
			l.append(v)
		for (k, f, v) in files:
			l.append('--' + boundary)
			l.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (k, f))
			l.append('Content-Type: %s' % self.__getContentType(f))
			l.append('')
			l.append(v)
		l.append('--' + boundary + '--')
		l.append('')
		body = crlf.join(l)

		return boundary, body

	def __getContentType(self, filename):
		return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

	def __postMultipart(self, path, fields=(), files=()):
		url = self.base_url + path

		(boundary, body) = self.__encodeMultipart(fields, files)
		headers = {'Content-Type': 'multipart/form-data; boundary=%s' % boundary,
			'Content-Length': str(len(body))
			}

		if self.use_oauth:
			headers = self.__makeOAuthHeader('POST', url, headers=headers)
		else:
			headers = self._makeAuthHeader(h)

		return http.getPage(url, method='POST',
			agent=self.agent,
			postdata=body, headers=headers)

	def __post(self, path, args={}):
		headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'}

		url = self.base_url + path

		if self.use_oauth:
			headers = self.__makeOAuthHeader('POST', url, args, headers)
		else:
			headers = self._makeAuthHeader(headers)

		return http.getPage(url, method='POST',
			agent=self.agent,
			postdata=self._urlencode(args), headers=headers)

	def _get(self, path, delegate, params, feed_factory=txml.Feed, extra_args=None):
		return self.__get(path, delegate, params, feed_factory, extra_args)

	def __get(self, path, delegate, params, feed_factory=txml.Feed, extra_args=None):
		url = self.base_url + path
		if params:
			url += '?' + self._urlencode(params)

		if self.use_auth:
			if self.use_oauth:
				headers = self.__makeOAuthHeader('GET', url)
			else:
				headers = self._makeAuthHeader()
		else:
			headers = {}
		factory = feed_factory(delegate, extra_args)
		d = http.downloadPage(url, factory, agent=self.agent, headers=headers)
		d.factory = factory
		return d

	def verify_credentials(self):
		"Verify a user's credentials."
		return self.__get('/account/verify_credentials.xml', None, None)

	def __parsed_post(self, hdef, parser):
		deferred = defer.Deferred()
		hdef.addErrback(lambda e: deferred.errback(e))
		hdef.addCallback(lambda p: deferred.callback(parser(p)))
		return deferred

	def update(self, status, source=None):
		"Update your status.  Returns the ID of the new post."
		params={'status': status}
		if source:
			params['source'] = source
		return self.__parsed_post(self.__post('/statuses/update.xml', params),
			txml.parseUpdateResponse)

	def friends2(self):
		o = CursorCollect(self, '/statuses/friends.xml', feed_type = txml.UserList)
		return o.defer

	def followers2(self):
		o = CursorCollect(self, '/statuses/followers.xml', feed_type = txml.UserList)
		return o.defer

	def friends(self, delegate, params={}, extra_args=None):
		"""Get updates from friends.

		Calls the delgate once for each status object received."""
		return self.__get('/statuses/friends_timeline.xml', delegate, params,
			txml.StatusList, extra_args=extra_args)

	def _get_list(self, url, delegate = None, params={}, extra_args=None, feed_type = txml.StatusList):
		do_delegate = False
		if not delegate:
			c = EntryCollect()
			do_delegate = True
			delegate = c.on_entry
		d = self.__get(url, delegate, params, feed_type, extra_args=extra_args)
		if do_delegate:
			d.addCallback(c.on_finish)
		return d

	def home_timeline(self, delegate = None, params={}, extra_args=None):
		"""Get updates from friends.

		Calls the delgate once for each status object received."""
		o = PageCollect(self, '/statuses/home_timeline.xml', params = params, feed_type = txml.StatusList)
		return o.defer
		#return self._get_list('/statuses/home_timeline.xml', delegate, params, extra_args)

	def user_timeline(self, delegate, user=None, params={}, extra_args=None):
		"""Get the most recent updates for a user.

		If no user is specified, the statuses for the authenticating user are
		returned.

		See search for example of how results are returned."""
		if user:
			params['id'] = user
		return self.__get('/statuses/user_timeline.xml', delegate, params,
						  txml.StatusList, extra_args=extra_args)

	def public_timeline(self, delegate, params={}, extra_args=None):
		"Get the most recent public timeline."

		return self.__get('/statuses/public_timeline.atom', delegate, params,
						  extra_args=extra_args)

	def direct_messages(self, delegate = None, params={}, extra_args=None):
		"""Get direct messages for the authenticating user.

		Search results are returned one message at a time a DirectMessage
		objects"""
		o = PageCollect(self, '/direct_messages.xml', params = params, feed_type = txml.Direct)
		return o.defer
		#return self._get_list('/direct_messages.xml', delegate, params, extra_args, feed_type = txml.Direct)

	def replies(self, delegate = None, params={}, extra_args=None):
		"""Get the most recent replies for the authenticating user.

		See search for example of how results are returned."""
		o = PageCollect(self, '/statuses/mentions.xml', params = params, feed_type = txml.StatusList)
		return o.defer
		#return self._get_list('/statuses/mentions.xml', delegate, params, extra_args)

	def follow(self, user):
		"""Follow the given user.

		Returns no useful data."""
		return self.__post('/friendships/create/%s.xml' % user)

	def leave(self, user):
		"""Stop following the given user.

		Returns no useful data."""
		return self.__post('/friendships/destroy/%s.xml' % user)

	def list_friends(self, delegate, user=None, params=None, extra_args=None):
		"""Get the list of friends for a user.

		Calls the delegate with each user object found."""
		if user:
			url = self.base_url + '/statuses/friends/' + user + '.xml'
		else:
			url = self.base_url + '/statuses/friends.xml'
		if params:
			url += '?' + self._urlencode(params)

		if self.use_oauth:
			headers = self.__makeOAuthHeader('GET', url)
		else:
			headers = self._makeAuthHeader()

		return client.downloadPage(url, txml.Users(delegate, extra_args),
			headers=headers)

	def list_followers(self, delegate, user=None, params=None, extra_args=None):
		"""Get the list of followers for a user.

		Calls the delegate with each user object found."""
		if user:
			url = self.base_url + '/statuses/followers/' + user + '.xml'
		else:
			url = self.base_url + '/statuses/followers.xml'
		if params:
			url += '?' + self._urlencode(params)

		if self.use_oauth:
			headers = self.__makeOAuthHeader('GET', url)
		else:
			headers = self._makeAuthHeader()

		return client.downloadPage(url, txml.Users(delegate, extra_args),
			headers=headers)

	def show_user(self, user):
		"""Get the info for a specific user.

		Returns a delegate that will receive the user in a callback."""

		url = '%s/users/show/%s.xml' % (self.base_url, user)
		d = defer.Deferred()
		if self.use_auth:
			if self.use_oauth:
				h = self.__makeOAuthHeader('GET', url)
			else:
				h = self._makeAuthHeader()
		else:
			h = {}

		client.downloadPage(url, txml.Users(lambda u: d.callback(u)),
			headers=h).addErrback(lambda e: d.errback(e))

		return d

	def search(self, query, delegate, args=None, extra_args=None):
		"""Perform a search query.

		Results are given one at a time to the delegate.  An example delegate
		may look like this:

		def exampleDelegate(entry):
			print entry.title"""
		if args is None:
			args = {}
		args['q'] = query
		return client.downloadPage(self.search_url + '?' + self._urlencode(args),
			txml.Feed(delegate, extra_args), agent=self.agent)

	def block(self, user):
		"""Block the given user.

		Returns no useful data."""
		return self.__post('/blocks/create/%s.xml' % user)

	def unblock(self, user):
		"""Unblock the given user.

		Returns no useful data."""
		return self.__post('/blocks/destroy/%s.xml' % user)

	def update_profile_image(self, filename, image):
		"""Update the profile image of an authenticated user.
		The image parameter must be raw data.

		Returns no useful data."""

		return self.__postMultipart('/account/update_profile_image.xml',
									files=(('image', filename, image),))

class TwitterFeed(Twitter):
	"""Realtime feed handling class.

	Results are given one at a time to the delegate.  An example delegate
	may look like this:

	def exampleDelegate(entry):
		print entry.text"""

	def _rtfeed(self, url, delegate, args):
		if args:
			url += '?' + self._urlencode(args)
		print 'Fetching', url
		return client.downloadPage(url, txml.HoseFeed(delegate), agent=self.agent,
								   headers=self._makeAuthHeader())

	def spritzer(self, delegate, args=None):
		"""Get the spritzer feed."""
		return self._rtfeed('http://stream.twitter.com/spritzer.xml', delegate, args)

	def gardenhose(self, delegate, args=None):
		"""Get the gardenhose feed."""
		return self._rtfeed('http://stream.twitter.com/gardenhose.xml', delegate, args)

	def firehose(self, delegate, args=None):
		"""Get the firehose feed."""

		return self._rtfeed('http://stream.twitter.com/firehose.xml', delegate, args)

	def follow(self, delegate, follow, method="follow"):
		"""Follow up to 200 users in realtime."""
		return self._rtfeed('http://stream.twitter.com/%s.xml' % method,
							delegate, {'follow': ','.join(follow)})

	def birddog(self, delegate, follow):
		"""Follow up to 200,000 users in realtime."""
		return self.follow(delegate, follow, 'birddog')

	def shadow(self, delegate, follow):
		"""Follow up to 2,000 users in realtime."""
		return self.follow(delegate, follow, 'shadow')

	def track(self, delegate, terms):
		"""Track up to 20 terms."""
		return self._rtfeed('http://stream.twitter.com/track.xml',
							delegate, {'track': ','.join(terms)})
