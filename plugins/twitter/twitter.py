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


    def _userid_to_item(self, itemid, entry):
        if itemid in self.users:
            return self._user_to_item(self.users[itemid], entry)
        for id in self.groups:
            gg = self.groups[id]['members']
            if itemid in gg:
                return self._user_to_item(gg[itemid])

    def _user_to_item(self, item, entry = None):
        if not entry:
            entry = message.Message('entry')
        entry.set('userid', item['id'])
        entry.set('user', item['name'])
        #entry.set('net', self.name)
        return entry

    def _on_users_come(self, arr, m = None, conn = None):
        #logging.debug('Users are here: %s', len(arr))
        self.users.clear()
        for user in arr:
            u = {}
            u['id'] = user.screen_name
            u['user_id'] = user.id
            u['name'] = user.name
            self.users[user.screen_name] = u
        self._update_tline()

    def _update_group_tline(self, group):
        cn, c = self.db.open_cursor()
        try:
            id = self._get_last_id(group['group_id'], c)

            params = {'since_id': id}
            d = self.twitter.list_timeline(group['user_id'], group['group_id'], params = params)
            d.addCallback(self._on_update_ok, type = 'normal', id_name = group['group_id'])
            d.addErrback(self._on_update_err, 'Error updating group %s' % group['group'])

            self.db.commit(cn)
        except Exception, err:
            logging.exception('Error while updating group timeline: %s', err)
            self.db.rollback(cn)


    def _on_group_users_come(self, arr, group, m = None, conn = None):
        #logging.debug('Group come: %s = %s', group['id'], len(arr))
        group['members'].clear()
        for user in arr:
            u = {}
            u['id'] = user.screen_name
            u['user_id'] = user.id
            u['name'] = user.name
            group['members'][user.screen_name] = u
        self._update_group_tline(group)

    def _update_users(self, m = None, conn = None):
        d = self.twitter.friends2()
        d.addCallback(self._on_users_come, m, conn)
        d.addErrback(self._on_update_err, 'Error fetching users', m, conn)

    def _on_group_updated(self, arr, group, m = None, conn = None, msg = None):
        if m and conn and msg:
            self.send_ok(msg, m, conn)
        #logging.debug('Group members updated: %s', arr)
        self._update_group(group)


    def _update_group(self, group, m = None, conn = None):
        d = self.twitter.list_members(group['user_id'], group['group_id'])
        d.addCallback(self._on_group_users_come, group, m, conn)
        d.addErrback(self._on_update_err, 'Error fetching list members', m, conn)


    def _on_groups_come(self, arr, m = None, conn = None, ok_message = None):
        #logging.debug('Groups: %s', len(arr))
        for item in arr:
            g = {}
            g['id'] = u'/'.join(reversed(item.uri.split('/')[1:]))
            g['list_id'] = item.uri
            g['group'] = item.uri
            g['group_id'] = item.id
            g['user_id'] = item.user.id
            g['members'] = {}
            #logging.debug('List: %s, %s', g['id'], g['group'])
            self.groups[g['id']] = g
            self._update_group(g)
        if ok_message:
            self.send_ok(ok_message, m, conn)

    def _on_group_del(self, arr, m = None, conn = None, ok_message = None):
        for item in arr:
            if item.uri in self.groups:
                del self.groups[item.uri]
        if ok_message:
            self.send_ok(ok_message, m, conn)
        self._update_lists()

    def _update_lists(self, m = None, conn = None):
        self.groups.clear()
        d = self.twitter.lists(self.user_id)
        d.addCallback(self._on_groups_come, m, conn)
        d.addErrback(self._on_update_err, 'Error fetching lists', m, conn)
        d = self.twitter.lists_subscriptions(self.user_id)
        d.addCallback(self._on_groups_come, m, conn)
        d.addErrback(self._on_update_err, 'Error fetching lists', m, conn)


    def init_twitter(self):
        tw = twitter.Twitter(self.get_setting('login'), self.get_setting('password'))
        d = tw.verify_credentials()
        def ok(arr):
            self.user_id = arr[0].id
            logging.debug('Complete init_twitter %s', arr[0].id)
            self.twitter = tw
            self.users.clear()
            self.groups.clear()
            self._update_users()
            self._update_lists()
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

    def _on_update_err(self, error, msg = None, m = None, conn = None):
        logging.error('We have error: %s', error)
        self.send_error(msg, m, conn)

    def _on_update_ok(self, arr, type = None, id_name = None):
        #logging.debug('Update complete %s, %s', type, len(arr))
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
                    groups = []
                    for gr in self.groups:
                        if _sender in self.groups[gr]['members']:
                            groups.append(gr)
                    m.set('groups', groups)
                    self._userid_to_item(_sender, m)
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

    def _update_by_timer(self):
        if not self.twitter:
            return
        
        self._update_users()
        self._update_lists()
        #self._update_tline()

        #for id in self.groups:
        #   g = self.groups[id]
        #   self._update_group_tline(g)

    def _update_tline(self):
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
        self.users = {}
        self.groups = {}
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
        self.refresh_task = LoopingCall(self._update_by_timer)
        self.refresh_task.start(self.get_intsetting('update_min', 5) * 60)
        self.init_twitter()
        return True

    def deactivate(self):
        logging.debug('Twitter %s is stopped', self.name)
        self.refresh_task.stop()

    def setting_changed(self, name, value):
        if name in ['login', 'password'] and not self.twitter:
            self.init_twitter()


    def new_message(self, m, connection):
        user = None
        group = None
        if m.name in ['unread_messages', 'mark_read']:
            u_text = m.get(('user', 'u'))
            if u_text:
                user = self.get_list_item(self.users, u_text)
                if not user:
                    for id in self.groups:
                        gr = self.groups[id]
                        u = self.get_list_item(gr['members'], u_text)
                        if u:
                            user = u
                            break
                if not user:
                    self.send_error('User not found', m, connection)
                    return True
            g_text = m.get(('group', 'g'))
            if g_text:
                group = self.get_list_item(self.groups, g_text)
                if not group:
                    self.send_error('Group not found', m, connection)
                    return True
            id = m.get('id')

        if m.name in ['unread_messages']:
            resp = message.response_message(m, 'unread_messages')
            cn, c = self.db.open_cursor()
            try:
                c.execute('select id_message, sender, body, date_received, type, id_tweet from messages where unread=1 order by date_received')
                arr = []
                for row in c:
                    if id and row[0]!=id:
                        continue
                    if user and row[1] != user['id']:
                        continue
                    if group:
                        if row[1] not in group['members']:
                            continue
                    #Pack message
                    mess = message.Message('message')
                    mess.set('messageid', row[0])
                    mess.set('userid', row[1])
                    self._userid_to_item(row[1], mess)
                    mess.set('message', row[2])
                    mess.set('type', row[4])
                    id_tweet = row[5]
                    mess.set('via', self.name)
                    _time = row[3]
                    _strtime = self.time_to_iso(_time)
                    mess.set('message-date', _strtime)
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
                    if id and r[0]!=id:
                        continue
                    if user and r[1] != user['id']:
                        continue
                    if group:
                        if r[1] not in group['members']:
                            continue
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

        if m.name in ['unread_users']:
            resp = message.response_message(m, 'unread_users')
            cn, c = self.db.open_cursor()
            try:
                c.execute('select sender, count(*) from messages where unread=1 group by sender')
                arr = []
                for r in c:
                    #Pack message
                    u = message.Message('user')
                    u.set('userid', r[0])
                    self._userid_to_item(r[0], u)
                    u.set('count', r[1])
                    arr.append(u)
                self.db.commit(cn)
                resp.set('users', arr)
                self.send_back(resp, connection)
            except Exception, err:
                self.db.rollback(cn)
                logging.exception('Error listing unread messages: %s', err)
                self.send_error('Error listing unread messages', m, connection)
            return True

        if m.name in ['unread_groups']:
            resp = message.response_message(m, 'unread_groups')
            cn, c = self.db.open_cursor()
            try:
                c.execute('select sender, count(*) from messages where unread=1 group by sender')
                arr = []
                data = {}
                for r in c:
                    #Pack message
                    data[r[0]] = r[1]
                for id in self.groups:
                    group = self.groups[id]
                    count = 0
                    for uid in group['members']:
                        if uid in data:
                            count = count + data[uid]
                    if count > 0:
                        g = message.Message('group')
                        g.set('groupid', group['id'])
                        g.set('group', group['group'])
                        g.set('count', count)
                        arr.append(g)
                self.db.commit(cn)
                resp.set('groups', arr)
                self.send_back(resp, connection)
            except Exception, err:
                self.db.rollback(cn)
                logging.exception('Error listing unread messages: %s', err)
                self.send_error('Error listing unread messages', m, connection)
            return True


        if not self.twitter:
            return False

        if m.name in ['users']:
            #No operations yet, just show
            a = []
            for id in self.users:
                a.append(self._user_to_item(self.users[id]))
            resp = message.response_message(m, 'users')
            resp.set('users', a)
            self.send_back(resp, connection)
            return True

        if m.name in ['groups']:
            #No operations yet
            if m.get('add'):
                gname = m.get('add')
                d = self.twitter.add_list(self.user_id, gname)
                d.addCallback(self._on_groups_come, m, connection, 'Group added')
                d.addErrback(self._on_update_err, 'Error while adding group', m, connection)
                return True
            if m.get('del'):
                gname = m.get('del')
                group = self.get_list_item(self.groups, gname)
                if not group:
                    self.send_error('Invalid group', m, connection)
                    return True
                d = self.twitter.del_list(self.user_id, group['group_id'])
                d.addCallback(self._on_group_del, m, connection, 'Group removed')
                d.addErrback(self._on_update_err, 'Error while removing group', m, connection)
                return True
            a = []
            for id in self.groups:
                g = self.groups[id]
                mess = message.Message('group')
                mess.set('groupid', id)
                mess.set('group', g['group'])
                a.append(mess)
            resp = message.response_message(m, 'groups')
            resp.set('groups', a)
            self.send_back(resp, connection)
            return True
        if m.name in ['group']:
            if m.get('add') or m.get('del'):
                group = m.get('add', m.get('del'))
                group = self.get_list_item(self.groups, group)
                if not group:
                    self.send_error('Invalid group', m, connection)
                    return True
                user = m.get('user')
                user = self.get_list_item(self.users, user)
                if not user:
                    self.send_error('Invalid user', m, connection)
                    return True
            if m.get('add'):
                d = self.twitter.add_list_member(group['user_id'], group['group_id'], user['user_id'])
                d.addCallback(self._on_group_updated, group, m, connection, 'Group member added')
                d.addErrback(self._on_update_err, 'Error while adding group member', m, connection)
                return True
            if m.get('del'):
                d = self.twitter.del_list_member(group['user_id'], group['group_id'], user['user_id'])
                d.addCallback(self._on_group_updated, group, m, connection, 'Group member removed')
                d.addErrback(self._on_update_err, 'Error while removing group member', m, connection)
                return True
            if m.get('show'):
                id = m.get('show')
                a = []
                group = self.get_list_item(self.groups, id)
                if group:
                    l = group['members']
                    #Enumerate all users
                    for id in l:
                        item = l[id]
                        e = message.Message('user')
                        a.append(self._user_to_item(item, e))
                    resp = message.response_message(m, 'group')
                    resp.set('entries', a)
                    self.send_back(resp, connection)
                else:
                    self.send_error('Invalid group', m)
                return True
        return False


def get_name():
    return 'twitter'

def get_description():
    return 'Twitter plugin'

def get_class():
    return TwitterPlugin
