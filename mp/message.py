#!/usr/bin/env python

from twisted.words.xish.domish import Element, elementStream
import logging

class Message:

    _messageId = 1

    def __init__(self, name = None, message = None):
        self.name = name
        self.properties = {}
        self.id = Message._messageId
        Message._messageId = Message._messageId+1
        if message:
            self.parse_xml(message)

    def parse_xml(self, message):
        if message.hasAttribute('id'):
            self.id = message['id']
        self.name = message.name
        for el in message.children:
            if el.getAttribute('type', '') == 'message':
                self.set(el.name, Message(None, el))
            elif el.getAttribute('type', '') == 'list':
                arr = []
                for itm in el.children:
                    if itm.getAttribute('type', '') == 'message':
                        arr.append(Message(None, itm))
                    else:
                        arr.append(unicode(itm))
                self.set(el.name, arr)
            else:
                self.set(el.name, unicode(el))

    def set(self, field, value):
        self.properties[field] = value

    def get(self, field, default = None):
        if isinstance(field, type(())):
            for name in field:
                if name in self.properties:
                    value = self.properties[name]
                    if value == '':
                        return None
                    return self.properties[name]
            return default
        if field not in self.properties:
            return default
        value = self.properties[field]
        if value == '':
            return None
        return self.properties[field]

    def keys(self):
        return self.properties.keys()

    def safe_unicode(self, obj, *args):
        """ return the unicode representation of obj """
        try:
            return unicode(obj, *args)
        except UnicodeDecodeError:
            # obj is byte string
            ascii_text = str(obj).encode('string_escape')
            return unicode(ascii_text)

    def _to_value(self, value):
        if isinstance(value, int):
            return unicode(value)
        if isinstance(value, unicode):
            return value
        #logging.debug('decoding to utf#1: %s: %s', value.__class__, value)
        #logging.debug('decoding to utf#2: %s', self.safe_unicode(value, 'utf-8'))
        #logging.debug('decoding to utf#3: %s', value.decode('utf-8'))
        return self.safe_unicode(value, 'utf-8')


    def to_xml(self, internal = False):
        result = Element(('', self._to_value(self.name)))
        result['type'] = 'message'
        if not internal:
            if self.id:
                result['id'] = unicode(self.id)
        for field in self.properties.keys():
            value = self.get(field)
            if isinstance(value, list):
                el = result.addElement(field)
                el['type'] = 'list'
                for item in value:
                    if isinstance(item, Message):
                        el.addChild(item.to_xml(True))
                    else:
                        el.addElement('item', content = self._to_value(item))
            elif isinstance(value, Message):
                result.addChild(value.to_xml(True))
            else:
                if value:
                    result.addElement(self._to_value(field), content = self._to_value(value))
        if internal:
            return result
        return result.toXml()

class StringToElement:
    result = None

    def on_element(self, element):
        self.result = element

    def onDocumentStart(self, rootElement):
        pass

    def onDocumentEnd(self):
        pass

    def __init__(self, src):
        try:
            stream = elementStream()
            stream.ElementEvent = self.on_element
            stream.DocumentStartEvent = self.onDocumentStart
            stream.DocumentEndEvent = self.onDocumentEnd
            stream.parse('<root>%s</root>' % (src))
        except Exception, err:
            logging.error("Error parsing XML from %s, %s", src, err)

def from_xml_string(xml):
    ste = StringToElement(xml)
    return Message(None, ste.result)

def response_message(m, name = None):
    mess = Message(m.name)
    if m.id:
        mess.id = m.id
    if name:
        mess.name = name
    if m.get('via'):
        mess.set('net', m.get('via'))
    return mess
