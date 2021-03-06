# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import glob
import importlib

from calvin.utilities import calvinuuid
from calvin.utilities.calvin_callback import CalvinCB
from calvin.utilities import calvinlogger
_log = calvinlogger.get_logger(__name__)

# FIXME should be read from calvin config
TRANSPORT_PLUGIN_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), *['south', 'plugins', 'transports'])
TRANSPORT_PLUGIN_NS = "calvin.runtime.south.plugins.transports"

class CalvinLink(object):
    """ CalvinLink class manage one RT to RT link between
        rt_id and peer_id using transport as mechanism.
        transport: a plug-in transport object
        old_link: should be supplied when we replace an existing link, will be closed
    """

    def __init__(self, rt_id, peer_id, transport, old_link=None):
        super(CalvinLink, self).__init__()
        self.rt_id = rt_id
        self.peer_id = peer_id
        self.transport = transport
        self.replies = old_link.replies if old_link else {}
        self.tunnels = old_link.tunnels if old_link else {}
        if old_link:
            old_link.close()

    def reply_handler(self, payload):
        """ Gets called when a REPLY messages arrives on this link """
        try:
            # Call the registered callback,for the reply message id, with the reply data as argument
            self.replies.pop(payload['msg_uuid'])(payload['value'])
        except:
            # We ignore unknown replies
            return

    def send_with_reply(self, callback, msg):
        """ Adds a message id to the message and send it,
            also registers the callback for the reply.
        """
        msg_id = calvinuuid.uuid("MSGID")
        self.replies[msg_id] = callback
        msg['msg_uuid'] = msg_id
        self.send(msg)

    def send(self, msg):
        """ Adds the from and to node ids to the message and 
            sends the message using the transport.

            The from and to node ids seems redundant since the link goes only between
            two nodes. But is included for verification and to later allow routing of messages.
        """
        msg['from_rt_uuid'] = self.rt_id
        msg['to_rt_uuid'] = self.peer_id
        self.transport.send(msg)

    def close(self):
        """ Disconnect the transport and hence the link object won't work anymore """
        self.transport.disconnect()

    def get_tunnel(self, tunnel_type=None):
        """get_tunnel return the first tunnel of tunnel_type if exist otherwise None"""
        if tunnel_type is None:
            # Currently only support get based on tunnel type
            return None
        try:
            return [t for t in self.tunnels.itervalues() if t.tunnel_type == tunnel_type][0]
        except:
            return None

class CalvinNetwork(object):
    """ CalvinNetwork keeps track of and establish all runtime to runtime links, 
        registers the transport plugins and start their listeners of incoming 
        join requests.

        The actual join protocol is handled by each transport plugin.

        TODO enable additional links to be established for other purposes
        than runtime to runtime communication, e.g. direct token transport etc.
    """

    def __init__(self, node):
        super(CalvinNetwork, self).__init__()
        self.node = node
        self.transport_modules = {}  # key module namespace string, value: imported module (must have register function)
        self.transports = {}  # key: URI schema, value: transport factory that handle URI
        self.links = {}  # key peer node id, value: CalvinLink obj
        self.recv_handler = None
        self.pending_joins = {}  # key: uri, value: list of callbacks or None
        self.pending_joins_by_id = {}  # key: peer id, value: uri

    def register_recv(self, recv_handler):
        """ Register THE function that will receive all incomming messages on all links """
        self.recv_handler = recv_handler

    def register(self, schemas, formats):
        """ Load and registers all transport plug-in modules matching the list of schemas.
            The plug-in modules can register any number of schemas with corresponding
            transport factory.
            The transports factories are objects that we can request a join according to a specific
            uri schema or start listening for incoming requests.
        """
        # Find python files in plugins/transport
        module_paths = glob.glob(os.path.join(TRANSPORT_PLUGIN_PATH, "*.py"))
        modules = [os.path.basename(f)[:-3] for f in module_paths if not os.path.basename(
            f).startswith('_') and os.path.isfile(f)]

        # Find directories with __init__.py python file (which should have the register function)
        module_paths = glob.glob(os.path.join(TRANSPORT_PLUGIN_PATH, "*"))
        dirs = [f for f in module_paths if not os.path.basename(f).startswith('_') and os.path.isdir(f)]
        modules += [os.path.basename(d) for d in dirs if os.path.isfile(os.path.join(d, "__init__.py"))]

        # Try to register each transport plugin module
        for m in modules:
            schema_objects = {}
            try:
                self.transport_modules[m] = importlib.import_module(TRANSPORT_PLUGIN_NS + "." + m)
                # Get a dictionary of schemas -> transport factory
                schema_objects = self.transport_modules[m].register(self.node.id,
                                                                    {'join_finished': [CalvinCB(self.join_finished)],
                                                                     'data_received': [self.recv_handler],
                                                                     'peer_disconnected': [CalvinCB(self.peer_disconnected)]},
                                                                    schemas, formats)
            except:
                _log.debug("Could not register transport plugin %s" % (m,), exc_info=True)
                continue
            _log.debug("Register transport plugin %s" % (m,))
            # Add them to the list - currently only one module can handle one schema
            self.transports.update(schema_objects)

    def start_listeners(self, uris=None):
        """ Start the transport listening on the uris 
            uris: optional list of uri strings. When not provided all schemas will be started.
                  a '<schema>:default' uri can be used to indicate that the transport should
                  use a default configuration, e.g. choose port number.
        """
        if not uris:
            uris = [schema + ":default" for schema in self.transports.keys()]

        for uri in uris:
            schema, addr = uri.split(':', 1)
            self.transports[schema].listen(uri)

    def join(self, uris, callback=None, corresponding_peer_ids=None):
        """ Join the peers accessable from list of URIs
            It is possible to have a list of corresponding peer_ids,
            which is used to filter the uris list for already connected
            or pending peer's connections.
            URI can't be used for matching since not neccessarily the same if peer connect to us
            uris: list of uris
            callback: will get called for each uri with arguments status='ACK'/'NACK' and uri
            corresponding_peer_ids: list of node ids matching the list of uris

            TODO: If corresponding_peer_ids is not specified it is possible that the callback is never called
            when a simultaneous join happens due to that it is not possible to detect by URI only.
            Should add a timeout that cleans out callbacks with NACK replies and let client retry.
        """
        # For each URI and when available a peer id
        for uri, peer_id in zip(uris,
                                corresponding_peer_ids if corresponding_peer_ids and
                                                           len(uris) == len(corresponding_peer_ids) 
                                                       else [None]*len(uris)):
            if not (uri in self.pending_joins or peer_id in self.pending_joins_by_id or peer_id in self.links):
                # No simultaneous join detected
                schema = uri.split(":",1)[0]
                if schema in self.transports.keys():
                    # store we have a pending join and its callback
                    if peer_id:
                        self.pending_joins_by_id[peer_id] = uri
                    if callback:
                        self.pending_joins[uri] = [callback]
                    # Ask the transport plugin to do the join
                    self.transports[schema].join(uri)
            else:
                # We have simultaneous joins
                if callback:
                    if peer_id in self.links:
                        # Link was already established, then need to call the callback now
                        callback(status="ACK", uri=uri)
                        continue
                    # Otherwise also want to be called when the ongoing link setup finishes
                    if uri in self.pending_joins:
                        self.pending_joins[uri].append(callback)
                    else:
                        self.pending_joins[uri] = [callback]

    def join_finished(self, tp_link, peer_id, uri, is_orginator):
        """ Peer join is (not) accepted, called by transport plugin.
            This may be initiated by us (is_orginator=True) or by the peer, 
            i.e. both nodes get called.
            When inititated by us pending_joins likely have a callback

            tp_link: the transport plugins object for the link (have send etc)
            peer_id: the node id we joined
            uri: the uri used for the join
            is_orginator: did this node request the join True/False
        """
        # while a link is pending it is the responsibility of the transport layer, since
        # higher layers don't have any use for it anyway
        _log.debug("Join finished for (%s, %s) with link: %s" % (peer_id, uri, tp_link))
        if tp_link is None:
            # This is a failed join lets send it upwards
            if uri in self.pending_joins:
                cbs = self.pending_joins.pop(uri)
                if cbs:
                    for cb in cbs:
                        cb(status="NACK", uri=uri)
            return
        # Only support for one RT to RT communication link per peer 
        if peer_id in self.links:
            # Likely simultaneous join requests, use the one requested by the node with highest id
            if is_orginator and self.node.id > peer_id:
                # We requested it and we have highest node id, hence the one in links is the peer's and we replace it
                _log.debug("Join finished for (%s, %s) BUT REPLACE since exist" % (peer_id, uri))
                self.links[peer_id] = CalvinLink(self.node.id, peer_id, tp_link, self.links[peer_id])
            elif is_orginator and self.node.id < peer_id:
                # We requested it and peer have highest node id, hence the one in links is peer's and we close this new
                _log.debug("Join finished for (%s, %s) BUT DROPPED since exist" % (peer_id, uri))
                tp_link.disconnect()
            elif not is_orginator and self.node.id > peer_id:
                # Peer requested it and we have highest node id, hence the one in links is ours and we close this new
                _log.debug("Join finished for (%s, %s) BUT DROPPED since exist" % (peer_id, uri))
                tp_link.disconnect()
            elif not is_orginator and self.node.id < peer_id:
                # Peer requested it and peer have highest node id, hence the one in links is ours and we replace it
                _log.debug("Join finished for (%s, %s) BUT REPLACE since exist" % (peer_id, uri))
                self.links[peer_id] = CalvinLink(self.node.id, peer_id, tp_link, self.links[peer_id])
        else:
            # No simultaneous join detected, just add the link
            _log.debug("Join finished for (%s, %s) inserted in links" % (peer_id, uri))
            self.links[peer_id] = CalvinLink(self.node.id, peer_id, tp_link)

        # Find and call any callbacks registered for the uri or peer id
        _log.debug("peer_id: %s, uri: %s\npending_joins_by_id: %s\npending_joins: %s" % (peer_id, 
                                                                                         uri, 
                                                                                         self.pending_joins_by_id, 
                                                                                         self.pending_joins))
        if peer_id in self.pending_joins_by_id:
            peer_uri = self.pending_joins_by_id.pop(peer_id)
            if peer_uri in self.pending_joins:
                cbs = self.pending_joins.pop(peer_uri)
                if cbs:
                    for cb in cbs:
                        cb(status="ACK", uri=peer_uri)

        if uri in self.pending_joins:
            cbs = self.pending_joins.pop(uri)
            if cbs:
                for cb in cbs:
                    cb(status="ACK", uri=uri)

        return

    def link_get(self, peer_id):
        """ Get a link by node id """
        return self.links.get(peer_id, None)

    def link_request(self, peer_id, callback=None):
        """ Request that a link is established. This is the prefered way
            of joining other nodes.
            peer_id: the node id that the link should be establieshed to
            callback: will get called with arguments status='ACK'/'NACK'/Exception and uri used
                      if the link needs to be established
            
            returns: True when link already exist, False when link needs to be established
        """
        if peer_id in self.links:
            return True
        _log.debug("Request for rt to rt (%s) link need to check storage" % (peer_id))
        # We don't have the peer, let's ask for it in storage
        self.node.storage.get_node(peer_id, CalvinCB(self.link_request_finished, callback=callback))
        return False

    def link_request_finished(self, key, value, callback):
        """ Called by storage when the node is (not) found """
        _log.debug("Request for rt to rt link storage returned (%s, %s)" % (key, value))
        # Test if value is None or False indicating node does not currently exist in storage
        if not value:
            # the peer_id did not exist in storage
            callback(status=Exception("Peer id %s could not be found in storage" % key))
            return

        # join the peer node
        _log.debug("Send join request for (%s, %s) CB: %s" % (key, value, callback))
        self.join([value['uri']], callback, [key])

    def peer_disconnected(self, link, rt_id, reason):
        self.link_remove(rt_id)

    def link_remove(self, peer_id):
        """ Removes a link to peer id """
        try:
            self.links.pop(peer_id)
        except:
            pass

    def link_check(self, rt_uuid):
        """ Check if we have the link otherwise raise exception """
        if rt_uuid not in self.links.iterkeys():
            raise Exception("ERROR_LINK_NOT_ESTABLISHED")

    def list_links(self):
        return list(self.links.keys())
