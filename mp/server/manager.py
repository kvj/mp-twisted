#!/usr/bin/env python

import logging
from mp import common, message
from mp.server import database
from twisted.internet import reactor
import os
import imp
import sys

class Rule:
    type = 'deny'
    entity = 'message'
    field = 'user'
    value = ''
    operation = '='
    plugin = ''
    xml = ''

class Globals:

    plugins = {}
    connections = []
    plugin_instances = {}
    rules = []
    master = None
    plugins_data = ''
    profile = None

class LoopbackConnection:

    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)

def filter_message(m):
    action = 'allow'
    #logging.debug('Filter: %s', m.to_xml())
    cn, c = Globals.master.open_cursor()
    try:
        for rule in Globals.rules:
            if rule.entity != m.name:
                continue
            if rule.plugin and rule.plugin != m.get('net'):
                continue
            result = False
            if rule.field == '*':
                #logging.debug('filter ok: *')
                result = True
            else:
                if m.get('userid') and rule.field == 'user':
                    #logging.debug('Filter by user')
                    if rule.plugin:
                        #Just compare two IDs
                        #logging.debug('Compare %s and %s', m.get('userid'), rule.value)
                        if m.get('userid').lower().startswith(rule.value.lower()):
                            #logging.debug('filter ok: user/plugin')
                            result = True
                    else:
                        #Select all virtual users where we have this user
                        c.execute('select user_id from users_entries ue, instances i where ue.instance_id=i.id and i.name=? and "user"=?', (m.get('net'), m.get('userid')))
                        for r in c:
                            #logging.debug('filter vuser %s and %s', r[0], rule.value)
                            if r[0] == rule.value:
                                #logging.debug('filter ok: vuser')
                                result = True
                elif rule.field == 'group':
                    if rule.plugin:
                        for group in m.get('groups', []):
                            #logging.debug('filter plugin/group %s and %s', group, rule.value)
                            if group.lower().startswith(rule.value.lower()):
                                #logging.debug('filter ok: group/plugin')
                                result = True
                    else:
                        #Virtual group here, go step by step
                        c.execute('select group_id from users_entries ue, instances i, groups_users gu where gu.user_id=ue.user_id and ue.instance_id=i.id and i.name=? and "user"=?', (m.get('net'), m.get('userid')))
                        for r in c:
                            #logging.debug('filter vuser-vgroup %s and %s', r[0], rule.value)
                            if r[0] == rule.value:
                                #logging.debug('filter ok vuser/vgroup')
                                result = True
                        c.execute('select "user", "group" from groups_entries ge, instances i where ge.instance_id=i.id and i.name=? and group_id=?', (m.get('net'), rule.value))
                        for r in c:
                            if r[0]:
                                #Check user
                                #logging.debug('filter vgroup-user %s %s', m.get('userid'), r[0])
                                if m.get('userid').lower() == r[0].lower():
                                    #logging.debug('filter ok: vgroup/user')
                                    result = True
                            if r[1]:
                                #Check group
                                #logging.debug('filter vgroup-group %s %s', r[1], m.get('groups', []))
                                if r[1] in m.get('groups', []):
                                    #logging.debug('filter ok vgroup/group')
                                    result = True
                else:
                    #logging.debug('filter other %s %s %s', rule.field, rule.value, m.get(rule.field))
                    if m.get(rule.field) == rule.value and rule.operation == '=':
                        #logging.debug('filter ok other')
                        result = True
            if result:
                action = rule.type
        Globals.master.commit(cn)
        return action
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while filtering: %s', err)
        #report_error(m, conn, 'Error while managing profile')
    return 'allow'

def deliver_message(instance, message, connection = None):
    message.set('net', instance.name)
    if connection:
        try:
            connection.send_message(message)
        except:
            pass
        return
    action = filter_message(message)
    if action != 'allow':
        logging.debug('message rejected[%s]: %s ', action, message.to_xml())
        return
    for conn in Globals.connections:
        try:
            conn.send_message(message)
        except:
            pass

def init_plugins():
    #Init database
    Globals.master = database.Database('%s/master.db' % (common.config.get('Server', 'db_dir')))
    #Create database schema

    seq = database.Table('messages')
    seq.add_id('id')
    seq.add_column('instance_id')
    Globals.master.add_table(seq)

    instances = database.Table('instances')
    instances.add_id('id')
    instances.add_column('name')
    instances.add_column('plugin')
    Globals.master.add_table(instances)

    settings = database.Table('settings')
    settings.add_id('id')
    settings.add_column('instance_id', 'INTEGER')
    settings.add_column('name')
    settings.add_column('value')
    Globals.master.add_table(settings)

    users = database.Table('users')
    users.add_id('id')
    users.add_column('name')
    Globals.master.add_table(users)

    users_entries = database.Table('users_entries')
    users_entries.add_id('id')
    users_entries.add_column('user_id', 'INTEGER')
    users_entries.add_column('instance_id', 'INTEGER')
    users_entries.add_column('user')
    Globals.master.add_table(users_entries)

    groups = database.Table('groups')
    groups.add_id('id')
    groups.add_column('name')
    Globals.master.add_table(groups)

    groups_entries = database.Table('groups_entries')
    groups_entries.add_id('id')
    groups_entries.add_column('group_id', 'INTEGER')
    groups_entries.add_column('instance_id', 'INTEGER')
    groups_entries.add_column('user')
    groups_entries.add_column('group')
    Globals.master.add_table(groups_entries)

    groups_users = database.Table('groups_users')
    groups_users.add_id('id')
    groups_users.add_column('group_id', 'INTEGER')
    groups_users.add_column('user_id', 'INTEGER')
    Globals.master.add_table(groups_users)

    profiles = database.Table('profiles')
    profiles.add_id('id')
    profiles.add_column('name')
    Globals.master.add_table(profiles)

    profiles_entries = database.Table('profiles_entries')
    profiles_entries.add_id('id')
    profiles_entries.add_column('profile_id', 'INTEGER')
    profiles_entries.add_column('profile')
    profiles_entries.add_column('command_name')
    profiles_entries.add_column('command')
    profiles_entries.add_column('order', 'INTEGER', default = 0)
    Globals.master.add_table(profiles_entries)

    if not Globals.master.verify_schema():
        return False

    #Load all plugins
    try:
        plugins_dir = common.config.get('Server', 'plugins_dir')
        logging.debug('Loading modules from %s...', plugins_dir)
        if os.path.isdir(plugins_dir):
            modules = os.listdir(plugins_dir)
            for f in modules:
                logging.debug('load module from %s', f)
                plugin_path = '%s/%s' % (plugins_dir, f)
                if not os.path.isdir(plugin_path):
                    continue
                try:
                    module = 'main'
                    try:
                        m = open('%s/manifest' % (plugin_path), 'r')
                        module = m.read().strip()
                        m.close()
                    except:
                        logging.debug('No manifest, use default module %s', module)
                    logging.debug('looking module %s in %s', module, plugin_path)
                    mod_file, mod_path, mod_desc = imp.find_module(module, [plugin_path])
                    if mod_file:
                        sys.path.append(plugin_path)
                        module = imp.load_module(module, mod_file, mod_path, mod_desc)
                        if module:
                            #Check plugin name and save class
                            plugin_name = module.get_name()
                            plugin_class = module.get_class()
                            if plugin_name and plugin_class:
                                logging.info('Loaded plugin: %s', plugin_name)
                                Globals.plugins[plugin_name] = module
                            pass
                        mod_file.close()
                except Exception, err:
                    logging.error('Can\'t load plugin %s: %s', f, err)
        else:
            logging.info('Plugins not found')
    except Exception, err:
        logging.error('Error loading plugins: %s')
        return False
    try:
        Globals.plugins_data = common.config.get('Server', 'plugins_data')
        if not os.path.isdir(Globals.plugins_data):
            os.mkdir(Globals.plugins_data)
    except Exception, err:
        logging.error('Error creating plugin data folder: %s', err)
        return False

    #Select and create instances
    conn, c = Globals.master.open_cursor()
    try:
        c.execute('select name, plugin, id from instances')
        for row in c:
            name = row[0]
            plugin = row[1]
            logging.debug('Creating instance of %s: %s', plugin, name)
            instance = load_instance(name, plugin, row[2])
            if not instance:
                continue
            #Load settings
            c2 = Globals.master.add_cursor(conn)
            c2.execute('select name, value from settings where instance_id=?', (row[2], ))
            for row2 in c2:
                instance.settings[row2[0]] = row2[1]
            instance.disabled = instance.get_boolsetting('disabled', False)
            if not instance.disabled:
                if not instance.activate():
                    #Remove instance
                    del Globals.plugin_instances[name]
        Globals.master.commit(conn)
    except Exception, err:
        Globals.master.rollback(conn)
        logging.exception('Error initializing plugins: %s', err)
        return False
    return True

def next_message_id(instance_id):
    cn, c = Globals.master.open_cursor()
    result = 1
    try:
        c.execute('insert into messages (instance_id) values (?)', (instance_id, ))
        result = c.lastrowid
        Globals.master.commit(cn)
    except:
        Globals.master.rollback(cn)
    return result

def load_instance(name, plugin, instance_id):
    instance = None
    if not plugin in Globals.plugins:
        logging.error('Can\'t find plugin %s', plugin)
    else:
        instance = Globals.plugins[plugin].get_class()()
        instance.name = name
        instance.type = plugin
        instance.instance_id = instance_id
        instance.settings = {}
        instance.disabled = False
        instance.db = database.Database('%s/%s.db' % (Globals.plugins_data, name))
        Globals.plugin_instances[name] = instance
    return instance

def report_error(m, conn, text):
    resp = message.response_message(m, 'error')
    resp.set('text', text)
    conn.send_message(resp)

def report_ok(m, conn, text = None):
    resp = message.response_message(m, 'ok')
    if text:
        resp.set('text', text)
    conn.send_message(resp)

def manage_networks(m, conn):
    if m.get('add'):
        plugin = m.get('add')
        if plugin in Globals.plugins:
            #Do add new instance
            alias = m.get('as', plugin)
            if alias in Globals.plugin_instances:
                report_error(m, conn, 'Alias already exists')
                return
            #Add entry to DB
            cn, c = Globals.master.open_cursor()
            instance_id = -1
            try:
                c.execute('select id from instances where name=?', (alias, ))
                r = c.fetchone()
                if not r:
                    c.execute('insert into instances (name, plugin) values (?, ?)', (alias, plugin))
                    instance_id = c.lastrowid
                else:
                    instance_id = r[0]
                Globals.master.commit(cn)
            except Exception, err:
                Globals.master.rollback(cn)
                logging.error('Error adding new instance: %s', err)
                report_error(m, conn, 'Can\'t add entry, DB error')
                return
            instance = load_instance(alias, plugin, instance_id)
            if not instance:
                logging.error('Can\'t create instance of %s', plugin)
                report_error(m, conn, 'Can\'t create instance')
                return
            if not instance.activate():
                #Remove instance
                del Globals.plugin_instances[alias]
            report_ok(m, conn)
        else:
            #Report error
            report_error(m, conn, 'Plugin not found')
        return

    if m.get('del'):
        plugin = m.get('del')
        if not plugin in Globals.plugin_instances:
            report_error(m, conn, 'No such entry')
            return
        cn, c = Globals.master.open_cursor()
        try:
            c.execute('select id from instances where name=?', (plugin, ))
            row = c.fetchone()
            c.execute('delete from settings where instance_id=?', (row[0], ))
            c.execute('delete from instances where id=?', (row[0], ))
            Globals.master.commit(cn)
        except:
            Globals.master.rollback(cn)
            report_error(m, conn, 'Error while removing entry')
            return
        if not Globals.plugin_instances[plugin].disabled:
            Globals.plugin_instances[plugin].deactivate()
        del Globals.plugin_instances[plugin]
        #Remove database and files
        report_ok(m, conn)
        return

    if m.get('opt'):
        plugin = m.get('opt')
        if not plugin in Globals.plugin_instances:
            report_error(m, conn, 'No such entry')
            return
        cn, c = Globals.master.open_cursor()
        try:
            c.execute('select id from instances where name=?', (plugin, ))
            row = c.fetchone() or [None]
            if m.get('name'):
                opt_name = m.get('name').lower()
                opt_value = m.get('value')
                c.execute('delete from settings where name=? and instance_id=?', (opt_name, row[0]))
                pl = Globals.plugin_instances[plugin]
                if opt_value:
                    logging.debug('Adding option %i, %s, %s', row[0], opt_name, opt_value)
                    c.execute('insert into settings (instance_id, name, value) values (?, ?, ?)', (row[0], opt_name, opt_value))
                    pl.settings[opt_name] = opt_value
                    if not pl.disabled:
                        pl.setting_changed(opt_name, opt_value)
                else:
                    if opt_name in pl.settings:
                        del pl.settings[opt_name]
                    if not pl.disabled:
                        pl.setting_changed(opt_name, None)
            resp = message.response_message(m, 'options')
            c.execute('select name, value from settings where instance_id=? order by name', (row[0], ))
            for r in c:
                resp.set(r[0], r[1])
            Globals.master.commit(cn)
            conn.send_message(resp)
            return
        except Exception, err:
            Globals.master.rollback(cn)
            logging.error('Error processing entry settings: %s', err)
            report_error(m, conn, 'Error processing entry options')
        return
    resp = message.response_message(m, 'networks')
    arr = []
    for name in Globals.plugin_instances.keys():
        instance = Globals.plugin_instances[name]
        entry = message.Message('network')
        entry.set('name', instance.name)
        entry.set('type', instance.type)
        if not instance.disabled:
            instance.fill_status(entry)
        else:
            entry.set('disabled', 'yes')
        arr.append(entry)
    resp.set('networks', arr)
    conn.send_message(resp)

def manage_user(m, conn):
    '''
    User details management
    '''
    cn, c = Globals.master.open_cursor()
    try:
        resp = message.response_message(m, 'user')
        user_id = -1
        if m.get('show'):
            user_id = int(m.get('show'))
        if m.get('add'):
            net = m.get('net')
            user_id = int(m.get('add'))
            user = m.get('user')
            c.execute('select id from instances where name=?', (net, ))
            r = c.fetchone()
            if r:
                net = r[0]
            else:
                net = None
            if not net or not user:
                logging.error('No network or no user provided')
                report_error(m, conn, 'No network or no user provided')
                Globals.master.rollback(cn)
                return

            c.execute('delete from users_entries where user_id=? and instance_id=? and lower(user)=?', (user_id, net, user.lower()))
            c.execute('insert into users_entries (user_id, instance_id, user) values (?, ?, ?)', (user_id, net, user.lower()))

        if m.get('del'):
            net = m.get('net')
            user_id = int(m.get('del'))
            user = m.get('user')
            c.execute('select id from instances where name=?', (net, ))
            r = c.fetchone()
            if r:
                net = r[0]
            else:
                net = None
            if not net or not user:
                logging.error('No network or no user provided')
                report_error(m, conn, 'No network or no user provided')
                Globals.master.rollback(cn)
                return

            c.execute('delete from users_entries where user_id=? and instance_id=? and lower(user)=?', (user_id, net, user.lower()))

        c.execute('select i.name, user from users_entries ue, instances i where ue.instance_id=i.id and user_id=? order by i.name, user', (user_id, ))
        ent = []
        for r in c:
            e = message.Message('entry')
            e.set('net', r[0])
            e.set('user', r[1])
            ent.append(e)
        resp.set('entries', ent)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.error('Error while managing user details: %s', err)
        report_error(m, conn, 'Error managing user details')

def manage_users(m, conn):
    '''
    User management
    Supported operations: new; list(default); view; to(rename); del; add; rem
    '''
    cn, c = Globals.master.open_cursor()
    try:
        resp = message.response_message(m, 'users')
        if m.get('add'):
            #Add new user, check name first
            user_name = m.get('add').strip()
            c.execute('select id from users where lower(name)=?', (user_name.lower(), ))
            if c.fetchone():
                Globals.master.rollback(cn)
                logging.error('User %s already exists', user_name)
                report_error(m, conn, 'User already exists')
                return
            #Add user
            c.execute('insert into users (name) values (?)', (user_name, ))
            resp.set('user_id', c.lastrowid)
        if m.get('del'):
            user_id = int(m.get('del'))
            c.execute('delete from users_entries where user_id=?', (user_id, ))
            c.execute('delete from groups_users where user_id=?', (user_id, ))
            c.execute('delete from users where id=?', (user_id, ))
        #List all users here
        c.execute('select id, name from users order by name')
        users = []
        for r in c:
            user = message.Message('user')
            user.set('userid', r[0])
            user.set('user', r[1])
            users.append(user)
        resp.set('users', users)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.error('Error while adding metauser %s', err)
        report_error(m, conn, 'Error adding new user')

def manage_group(m, conn):
    '''
    User group management
    '''
    cn, c = Globals.master.open_cursor()
    try:
        resp = message.response_message(m, 'group')
        group_id = -1

        user = m.get('user')
        group = m.get('group')
        if user:
            user = user.lower()
        if group:
            group = group.lower()

        if m.get('show'):
            group_id = int(m.get('show'))
        if m.get('add'):
            net = m.get('net')
            group_id = int(m.get('add'))
            if not net:
                #Add meta-user
                c.execute('select id from users where id=?', (user, ))
                if not c.fetchone():
                    logging.error('Invalid user provided')
                    report_error(m, conn, 'Invalid user provided')
                    Globals.master.rollback(cn)
                    return
                c.execute('delete from groups_users where group_id=? and user_id=?', (group_id, user))
                c.execute('insert into groups_users (group_id, user_id) values (?, ?)', (group_id, user))
            else:
                c.execute('select id from instances where name=?', (net, ))
                r = c.fetchone()
                if r:
                    net = r[0]
                else:
                    net = None
                if not net or (not user and not group):
                    logging.error('No network or no user provided')
                    report_error(m, conn, 'No network or no user provided')
                    Globals.master.rollback(cn)
                    return

                c.execute('delete from groups_entries where group_id=? and instance_id=? and lower("user")=? and lower("group")=?', (group_id, net, user, group))
                c.execute('insert into groups_entries (group_id, instance_id, "user", "group") values (?, ?, ?, ?)', (group_id, net, user, group))

        if m.get('del'):
            group_id = int(m.get('del'))
            net = m.get('net')
            if not net:
                #Delete meta-user
                c.execute('select id from users where id=?', (user, ))
                if not c.fetchone():
                    logging.error('Invalid user provided')
                    report_error(m, conn, 'Invalid user provided')
                    Globals.master.rollback(cn)
                    return
                c.execute('delete from groups_users where group_id=? and user_id=?', (group_id, user))
            else:
                c.execute('select id from instances where name=?', (net, ))
                r = c.fetchone()
                if r:
                    net = r[0]
                else:
                    net = None
                if not net or (not user and not group):
                    logging.error('No network or no user provided')
                    report_error(m, conn, 'No network or no user provided')
                    Globals.master.rollback(cn)
                    return
                if user:
                    c.execute('delete from groups_entries where group_id=? and instance_id=? and lower("user")=?', (group_id, net, user))
                else:
                    c.execute('delete from groups_entries where group_id=? and instance_id=? and lower("group")=?', (group_id, net, group))

        c.execute('select i.name, "user", "group" from groups_entries ge, instances i where ge.instance_id=i.id and group_id=? order by i.name, "user", "group"', (group_id, ))
        ent = []
        for r in c:
            e = message.Message('entry')
            e.set('net', r[0])
            if r[1]:
                e.set('user', r[1])
            if r[2]:
                e.set('group', r[2])
            ent.append(e)
        c.execute('select u.name from users u, groups_users gu where gu.user_id=u.id and group_id=? order by name', (group_id, ))
        for r in c:
            e = message.Message('entry')
            e.set('user', r[0])
            ent.append(e)

        resp.set('entries', ent)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while managing group details: %s', err)
        report_error(m, conn, 'Error managing group details')

def manage_groups(m, conn):
    '''
    Group management
    Supported operations: add; del
    '''
    cn, c = Globals.master.open_cursor()
    try:
        resp = message.response_message(m, 'groups')
        if m.get('add'):
            #Add new group, check name first
            group_name = m.get('add').strip()
            c.execute('select id from groups where lower(name)=?', (group_name.lower(), ))
            if c.fetchone():
                Globals.master.rollback(cn)
                logging.error('Group %s already exists', group_name)
                report_error(m, conn, 'Group already exists')
                return
            #Add group
            c.execute('insert into groups (name) values (?)', (group_name, ))
            resp.set('group_id', c.lastrowid)
        if m.get('del'):
            group_id = int(m.get('del'))
            c.execute('delete from groups_entries where group_id=?', (group_id, ))
            c.execute('delete from groups_users where group_id=?', (group_id, ))
            c.execute('delete from groups where id=?', (group_id, ))
        #List all groups here
        c.execute('select id, name from groups order by name')
        groups = []
        for r in c:
            group = message.Message('group')
            group.set('groupid', r[0])
            group.set('group', r[1])
            groups.append(group)
        resp.set('groups', groups)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while adding metagroup %s', err)
        report_error(m, conn, 'Error adding new group')

def manage_plugins(m, conn):
    #By default, send back list of loaded plugins
    resp = message.response_message(m, 'plugins')
    for name in Globals.plugins.keys():
        resp.set(name, Globals.plugins[name].get_description())
    conn.send_message(resp)

def message_to_plugin(m, conn):
    net = m.get('via')
    result = False
    if net in Globals.plugin_instances:
        plugin = Globals.plugin_instances[net]
        if not plugin.disabled:
            result = plugin.new_message(m, conn)
    if not result:
        report_error(m, conn, 'Command isn\'t supported by plugin')

def get_data_from_plugins(mess, c, field, default = []):
    uu = {}
    for net in Globals.plugin_instances:
        lc = LoopbackConnection()
        plugin = Globals.plugin_instances[net]
        if plugin.disabled:
            continue
        plugin.new_message(mess, lc)
        if len(lc.messages)>0:
            c.execute('select id from instances where name=?', (net, ))
            row = c.fetchone()
            if row:
                uu[row[0]] = (net, lc.messages[0].get(field, default))
    return uu

def get_data_from_plugin(net_id, mess, c):
    c.execute('select name from instances where id=?', (net_id, ))
    row = c.fetchone()
    if row and row[0] in Globals.plugin_instances:
        lc = LoopbackConnection()
        plugin = Globals.plugin_instances[row[0]]
        if plugin.disabled:
            return None
        plugin.new_message(mess, lc)
        if len(lc.messages)>0:
            return lc.messages[0]
    return None


def manage_status(m, conn):
    for id in Globals.plugin_instances:
        pl = Globals.plugin_instances[id]
        if not pl.disabled:
            pl.new_message(m, conn)


def manage_reply(m, conn):
    cn, c = Globals.master.open_cursor()
    try:
        c.execute('select instance_id from messages where id=?', (m.get('to', -1), ))
        r = c.fetchone()
        if not r:
            report_error(m, conn, 'Invalid message for reply')
            Globals.master.commit(cn)
            return
        instance_id = int(r[0])
        for id in Globals.plugin_instances:
            pl = Globals.plugin_instances[id]
            if pl.instance_id==instance_id and not pl.disabled:
                pl.new_message(m, conn)
                Globals.master.commit(cn)
                return
    except Exception, err:
        logging.exception('Error while manage_reply: %s', err)
    Globals.master.rollback(cn)
    report_error(m, conn, 'Invalid reply, plugin not found')


def manage_unread_users(m, conn):
    #Collect all unread users from all plugins
    cn, c = Globals.master.open_cursor()
    try:
        mess = message.Message('unread_users')
        uu = get_data_from_plugins(mess, c, 'users')
        #Fetch all users
        c2 = Globals.master.add_cursor(cn)
        c.execute('select id, name from users')
        users = []
        for row in c:
            count = 0
            c2.execute('select user, instance_id from users_entries where user_id=?', (row[0], ))
            for row2 in c2:
                if row2[1] in uu:
                    net, arr = uu[row2[1]]
                    for mess in arr:
                        if mess.get('userid') == row2[0]:
                            count = count + int(mess.get('count', 0))
            if count>0:
                u = message.Message('user')
                u.set('userid', row[0])
                u.set('user', row[1])
                u.set('count', count)
                users.append(u)
        resp = message.response_message(m, 'unread_users')
        resp.set('users', users)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while manage_unread_users: %s', err)
        report_error(m, conn, 'Error while listing unread users')

def manage_unread_networks(m, conn):
    cn, c = Globals.master.open_cursor()
    try:
        mess = message.Message('unread_messages')
        um = get_data_from_plugins(mess, c, 'messages', [])
        arr = []
        for id in Globals.plugin_instances:
            pl = Globals.plugin_instances[id]
            #logging.debug('un: %s, %s, %s', id, pl.disabled, um)
            if pl.disabled or pl.instance_id not in um:
                continue
            net, marr = um[pl.instance_id]
            if len(marr)<1:
                continue
            n = message.Message('net')
            n.set('name', id)
            n.set('count', len(marr))
            arr.append(n)
        resp = message.response_message(m, 'unread_networks')
        resp.set('networks', arr)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while manage_unread_networks: %s', err)
        report_error(m, conn, 'Error while listing unread networks')


def manage_unread_messages(m, conn):
    #Collect all unread users from all plugins
    cn, c = Globals.master.open_cursor()
    try:
        mess = message.Message('unread_messages')
        um = get_data_from_plugins(mess, c, 'messages')
        user = m.get('user')
        group = m.get('group')
        if user:
            user = user.lower()
        if group:
            group = group.lower()
        messages = []
        c2 = Globals.master.add_cursor(cn)
        if user:
            #Fetch all users
            c.execute('select user, instance_id from users_entries where user_id=?', (user, ))
            for row in c:
                if row[1] in um:
                    net, arr = um[row[1]]
                    for mess in arr:
                        if mess.get('userid') == row[0]:
                            messages.append(mess)
        elif group:
            c2.execute('select user_id from groups_users where group_id=?', (group, ))
            for row2 in c2:
                c.execute('select user, instance_id from users_entries where user_id=?', (row2[0], ))
                for row in c:
                    if row[1] in um:
                        net, arr = um[row[1]]
                        for mess in arr:
                            if mess.get('userid') == row[0]:
                                messages.append(mess)
            c2.execute('select "user", "group", instance_id from groups_entries where group_id=?', (group, ))
            for row2 in c2:
                if row2[0] and row2[2] in um:
                    net, arr = um[row2[2]]
                    for mess in arr:
                        if mess.get('userid') == row2[0]:
                            messages.append(mess)
                if row2[1]:
                    mess = message.Message('unread_messages')
                    mess.set('group', row2[1])
                    ugm = get_data_from_plugins(mess, c, 'messages')
                    for id in ugm:
                        net, arr = ugm[id]
                        for mess in arr:
                            messages.append(mess)
        else:
            report_error(m, conn, 'Please specify user or group')
            Globals.master.commit(cn)
            return

        resp = message.response_message(m, 'unread_messages')
        resp.set('messages', messages)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while manage_unread_users: %s', err)
        report_error(m, conn, 'Error while listing unread users')

def manage_mark_read(m, conn):
    cn, c = Globals.master.open_cursor()
    try:
        user = m.get('user')
        group = m.get('group')
        if user:
            user = user.lower()
        if group:
            group = group.lower()
        count = 0
        messages = []
        c2 = Globals.master.add_cursor(cn)
        c3 = Globals.master.add_cursor(cn)
        if user:
            #Fetch all users
            c.execute('select user, instance_id from users_entries where user_id=?', (user, ))
            for row in c:
                mess = message.Message('mark_read')
                mess.set('user', row[0])
                rep = get_data_from_plugin(row[1], mess, c2)
                if rep:
                    messages.extend(rep.get('messages', []))
                    count = count + len(rep.get('messages', []))
        elif group:
            c2.execute('select user_id from groups_users where group_id=?', (group, ))
            for row2 in c2:
                c.execute('select user, instance_id from users_entries where user_id=?', (row2[0], ))
                for row in c:
                    mess = message.Message('mark_read')
                    mess.set('user', row[0])
                    rep = get_data_from_plugin(row[1], mess, c3)
                    if rep:
                        messages.extend(rep.get('messages', []))
                        count = count + len(rep.get('messages', []))
            c2.execute('select "user", "group", instance_id from groups_entries where group_id=?', (group, ))
            for row2 in c2:
                if row2[0]:
                    mess = message.Message('mark_read')
                    mess.set('user', row2[0])
                    rep = get_data_from_plugin(row2[2], mess, c3)
                    if rep:
                        messages.extend(rep.get('messages', []))
                        count = count + len(rep.get('messages', []))
                if row2[1]:#Group
                    mess = message.Message('mark_read')
                    mess.set('group', row2[1])
                    rep = get_data_from_plugin(row2[2], mess, c3)
                    if rep:
                        messages.extend(rep.get('messages', []))
                        count = count + len(rep.get('messages', []))
        else:
            report_error(m, conn, 'Please specify user or group')
            Globals.master.commit(cn)
            return

        resp = message.response_message(m, 'mark_read')
        resp.set('messages', messages)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while mark_read: %s', err)
        report_error(m, conn, 'Error while marking messages as read')

def manage_unread_groups(m, conn):
    #Collect all unread users from all plugins
    cn, c = Globals.master.open_cursor()
    try:
        mess = message.Message('unread_users')
        uu = get_data_from_plugins(mess, c, 'users')
        mess = message.Message('unread_groups')
        ug = get_data_from_plugins(mess, c, 'groups')
        #Fetch all users
        c2 = Globals.master.add_cursor(cn)
        c3 = Globals.master.add_cursor(cn)
        c.execute('select id, name from groups')
        groups = []
        for row in c:
            count = 0
            c3.execute('select user_id from groups_users where group_id=?', (row[0], ))
            for row3 in c3:
                c2.execute('select user, instance_id from users_entries where user_id=?', (row3[0], ))
                for row2 in c2:
                    if row2[1] in uu:
                        net, arr = uu[row2[1]]
                        for mess in arr:
                            if mess.get('userid') == row2[0]:
                                count = count + int(mess.get('count', 0))
            c2.execute('select "user", "group", instance_id from groups_entries where group_id=?', (row[0], ))
            for row2 in c2:
                if row2[2] in uu:#instance_id
                    net, arr = uu[row2[2]]
                    for mess in arr:
                        if mess.get('userid') == row2[0]:
                            count = count + int(mess.get('count', 0))
                if row2[2] in ug:
                    net, arr = ug[row2[2]]
                    for mess in arr:
                        if mess.get('groupid') == row2[1]:
                            count = count + int(mess.get('count', 0))
            if count>0:
                u = message.Message('group')
                u.set('groupid', row[0])
                u.set('group', row[1])
                u.set('count', count)
                groups.append(u)
        resp = message.response_message(m, 'unread_groups')
        resp.set('groups', groups)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while manage_unread_groups: %s', err)
        report_error(m, conn, 'Error while listing unread groups')

def manage_profile(m, conn):
    """
    Profile management
    """
    cn, c = Globals.master.open_cursor()
    try:
        if m.get('set'):
            """
            Setting up profile, execute all entries
            """
            Globals.profile = m.get('set')
            c.execute('select command from profiles_entries where profile=? order by id', (Globals.profile, ))
            Globals.rules = []
            lc = LoopbackConnection()
            for r in c:
                command = r[0]
                mess = message.from_xml_string(command)
                process_message(mess, lc)
            report_ok(m, conn, 'Profile set')
            Globals.master.commit(cn)
            return
        if not Globals.profile:
            report_error(m, conn, 'Profile is empty, please activate one')
            Globals.master.rollback(cn)
            return
        if m.get('add') and m.get(m.get('add')):
            cname = m.get('add')
            command = m.get(cname)
            c.execute('insert into profiles_entries (profile, command_name, command) values (?, ?, ?)', (Globals.profile, cname, command.to_xml()))
            report_ok(m, conn, 'Profile entry added')
            Globals.master.commit(cn)
            return
        if m.get('del'):
            if m.get('del') == 'all':
                c.execute('delete from profiles_entries where profile=?', (Globals.profile, ))
            else:
                index = int(m.get('del'))
                c.execute('select id from profiles_entries where profile=? order by id', (Globals.profile, ))
                i = 0
                for r in c:
                    if index == i:
                        c.execute('delete from profiles_entries where id=?', (r[0], ))
                        break;
                    else:
                        i = i + 1
            report_ok(m, conn, 'Profile entry removed')
            Globals.master.commit(cn)
            return
        if m.get('use', '') == 'rules':
#Save all current rules for profile
            c.execute('delete from profiles_entries where profile=? and command_name=?', (Globals.profile, 'rule'))
            for r in Globals.rules:
                c.execute('insert into profiles_entries (profile, command_name, command) values (?, ?, ?)', (Globals.profile, 'rule', r.xml))
            report_ok(m, conn, 'Profile entries updated')
            Globals.master.commit(cn)
            return
#List all profile entries
        resp = message.response_message(m, 'profile')
        c.execute('select command from profiles_entries where profile=? order by id', (Globals.profile, ))
        arr = []
        for r in c:
            logging.debug('XML is: %s', r[0])
            mess = message.from_xml_string(r[0])
            if mess:
                arr.append(mess)
        resp.set('commands', arr)
        conn.send_message(resp)
        Globals.master.commit(cn)
    except Exception, err:
        Globals.master.rollback(cn)
        logging.exception('Error while manage_profile: %s', err)
        report_error(m, conn, 'Error while managing profile')


def manage_rules(m, conn):
    """
    Block messages rule management
    """
#    cn, c = Globals.master.open_cursor()
    try:
#        Globals.master.commit(cn)
        if m.get('add'):
            #add new rule
            rule = Rule()
            rule.xml = m.to_xml()
            rule.type = m.get('add')
            rule.field = m.get('field')
            if not rule.field:
                rule.field = '*'
            if m.get('is'):
                rule.value = m.get('is')
            rule.plugin = m.get('via')
            before = int(m.get('before', len(Globals.rules)))
            if before<len(Globals.rules):
                Globals.rules.insert(before, rule)
            else:
                Globals.rules.append(rule)
            report_ok(m, conn, 'Rule added')
            return
        if m.get('del'):
            if m.get('del') == 'all':
                Globals.rules = []
                report_ok(m, conn, 'Rules cleared')
                return
            index = int(m.get('del', -1))
            if index >= 0 and index < len(Globals.rules):
                Globals.rules.remove(Globals.rules[index])
                report_ok(m, conn, 'Rule removed')
            else:
                report_error(m, conn, 'Invalid rule index')
            return
#Show rules
        resp = message.response_message(m, 'rules')
        arr = []
        for r in Globals.rules:
            rule = message.Message('rule')
            rule.set('type', r.type)
            rule.set('field', r.field)
            rule.set('value', r.value)
            rule.set('op', r.operation)
            rule.set('plugin', r.plugin)
            arr.append(rule)
        resp.set('rules', arr)
        conn.send_message(resp)
    except Exception, err:
#        Globals.master.rollback(cn)
        logging.exception('Error while manage_rules: %s', err)
        report_error(m, conn, 'Error while managing block rules')


def process_message(message, connection):
    #logging.debug('Message %s', message.name)

    if message.name in ['shutdown']:
        try:
            reactor.stop()
            if common.daemon:
                common.daemon.delpid()
        except:
            pass
        return

    if message.name in ['plugins']:
        manage_plugins(message, connection)
        return

    if message.name in ['net']:
        manage_networks(message, connection)
        return

    if message.name in ['reply']:
        manage_reply(message, connection)
        return

    if message.name in ['unread_networks']:
        manage_unread_networks(message, connection)
        return

    if message.name in ['profile']:
        manage_profile(message, connection)
        return

    if message.name in ['rule']:
        manage_rules(message, connection)
        return

    if message.get('via'):
        message_to_plugin(message, connection)
        return

    if message.name in ['status']:
        manage_status(message, connection)
        return

    if message.name in ['users']:
        manage_users(message, connection)
        return

    if message.name in ['groups']:
        manage_groups(message, connection)
        return

    if message.name in ['user']:
        manage_user(message, connection)
        return

    if message.name in ['group']:
        manage_group(message, connection)
        return

    if message.name in ['unread_users']:
        manage_unread_users(message, connection)
        return

    if message.name in ['unread_groups']:
        manage_unread_groups(message, connection)
        return

    if message.name in ['mark_read']:
        manage_mark_read(message, connection)
        return

    if message.name in ['unread_messages']:
        manage_unread_messages(message, connection)
        return

    report_error(message, connection, 'Invalid command')


def client_connected(connection):
    logging.debug('New client connected')
    Globals.connections.append(connection)

def client_disconnected(connection):
    logging.debug('Client disconnected')
    Globals.connections.remove(connection)
