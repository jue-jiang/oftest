"""
Flow query test case.

Attempts to fill switch to capacity with randomized flows, and ensure that
they all are read back correctly.
"""
import math

import logging

import unittest
import random

import oftest.controller  as controller
import oftest.cstruct     as ofp
import oftest.message     as message
import oftest.dataplane   as dataplane
import oftest.action      as action
import oftest.action_list as action_list
import oftest.parse       as parse
import pktact
import basic

from testutils import *
from time import sleep

#@var port_map Local copy of the configuration map from OF port
# numbers to OS interfaces
pa_port_map = None
#@var pa_logger Local logger object
pa_logger = None
#@var pa_config Local copy of global configuration data
pa_config = None

# For test priority
test_prio = {}


def test_set_init(config):
    """
    Set up function for packet action test classes

    @param config The configuration dictionary; see oft
    """

    basic.test_set_init(config)

    global pa_port_map
    global pa_logger
    global pa_config

    pa_logger = logging.getLogger("pkt_act")
    pa_logger.info("Initializing test set")
    pa_port_map = config["port_map"]
    pa_config = config

    # TBD - Doesn't seem to take effect at the right time...
    if test_param_get(pa_config, "dut", "") == "ovs":
        # Disable this test by default, since the flow capacity
        # reported by OVS is bogus.
        test_prio["Flow_Add_6"] = -1


def flip_coin():
    return random.randint(1, 100) <= 50


def shuffle(list):
    n = len(list)
    lim = n * n
    i = 0
    while i < lim:
        a = random.randint(0, n - 1)
        b = random.randint(0, n - 1)
        temp = list[a]
        list[a] = list[b]
        list[b] = temp
        i = i + 1
    return list


def rand_pick(list):
    return list[random.randint(0, len(list) - 1)]

def rand_dl_addr():
    return [random.randint(0, 255) & ~1,
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255)
            ]

def rand_nw_addr():
    return random.randint(0, (1 << 32) - 1)


class Flow_Info:
    # Members:
    # priorities - list of flow priorities
    # dl_addrs   - list of MAC addresses
    # vlans      - list of VLAN ids
    # ethertypes - list of Ethertypes
    # ip_addrs   - list of IP addresses
    # ip_tos     - list of IP TOS values
    # ip_protos  - list of IP protocols
    # l4_ports   - list of L4 ports

    def __init__(self):
        priorities = []
        dl_addrs   = []
        vlans      = []
        ethertypes = []
        ip_addrs   = []
        ip_tos     = []
        ip_protos  = []
        l4_ports   = []

    def rand(self, n):
        self.priorities = []
        i = 0
        while i < n:
            self.priorities.append(random.randint(1, 65534))
            i = i + 1
    
        self.dl_addrs = []
        i = 0
        while i < n:
            self.dl_addrs.append(rand_dl_addr())
            i = i + 1
    
        self.vlans = []
        i = 0
        while i < n:
            self.vlans.append(random.randint(1, 4094))
            i = i + 1
    
        self.ethertypes = [0x0800, 0x0806]
        i = 0
        while i < n:
            self.ethertypes.append(random.randint(0, (1 << 16) - 1))
            i = i + 1
        self.ethertypes = shuffle(self.ethertypes)[0 : n]
    
        self.ip_addrs = []
        i = 0
        while i < n:
            self.ip_addrs.append(rand_nw_addr())
            i = i + 1
    
        self.ip_tos = []
        i = 0
        while i < n:
            self.ip_tos.append(random.randint(0, (1 << 8) - 1) & ~3)
            i = i + 1
    
        self.ip_protos = [1, 6, 17]
        i = 0
        while i < n:
            self.ip_protos.append(random.randint(0, (1 << 8) - 1))
            i = i + 1
        self.ip_protos = shuffle(self.ip_protos)[0 : n]
    
        self.l4_ports = []
        i = 0
        while i < n:
            self.l4_ports.append(random.randint(0, (1 << 16) - 1))
            i = i + 1

    def rand_priority(self):
        return rand_pick(self.priorities)

    def rand_dl_addr(self):
        return rand_pick(self.dl_addrs)

    def rand_vlan(self):
        return rand_pick(self.vlans)

    def rand_ethertype(self):
        return rand_pick(self.ethertypes)

    def rand_ip_addr(self):
        return rand_pick(self.ip_addrs)

    def rand_ip_tos(self):
        return rand_pick(self.ip_tos)

    def rand_ip_proto(self):
        return rand_pick(self.ip_protos)

    def rand_l4_port(self):
        return rand_pick(self.l4_ports)


# TBD - These don't belong here

all_wildcards_list = [ofp.OFPFW_IN_PORT,
                      ofp.OFPFW_DL_DST,
                      ofp.OFPFW_DL_SRC,
                      ofp.OFPFW_DL_VLAN,
                      ofp.OFPFW_DL_VLAN_PCP,
                      ofp.OFPFW_DL_TYPE,
                      ofp.OFPFW_NW_TOS,
                      ofp.OFPFW_NW_PROTO,
                      ofp.OFPFW_NW_SRC_MASK,
                      ofp.OFPFW_NW_DST_MASK,
                      ofp.OFPFW_TP_SRC,
                      ofp.OFPFW_TP_DST
                      ]

# TBD - Need this because there are duplicates in ofp.ofp_flow_wildcards_map
# -- FIX
all_wildcard_names = {
    1                               : 'OFPFW_IN_PORT',
    2                               : 'OFPFW_DL_VLAN',
    4                               : 'OFPFW_DL_SRC',
    8                               : 'OFPFW_DL_DST',
    16                              : 'OFPFW_DL_TYPE',
    32                              : 'OFPFW_NW_PROTO',
    64                              : 'OFPFW_TP_SRC',
    128                             : 'OFPFW_TP_DST',
    1048576                         : 'OFPFW_DL_VLAN_PCP',
    2097152                         : 'OFPFW_NW_TOS'
}


def wildcard_set(x, w, val):
    result = x
    if w == ofp.OFPFW_NW_SRC_MASK:
        result = (result & ~ofp.OFPFW_NW_SRC_MASK) \
                 | (val << ofp.OFPFW_NW_SRC_SHIFT)
    elif w == ofp.OFPFW_NW_DST_MASK:
        result = (result & ~ofp.OFPFW_NW_DST_MASK) \
                 | (val << ofp.OFPFW_NW_DST_SHIFT)
    elif val == 0:
        result = result & ~w
    else:
        result = result | w
    return result

def wildcard_get(x, w):
    if w == ofp.OFPFW_NW_SRC_MASK:
        return (x & ofp.OFPFW_NW_SRC_MASK) >> ofp.OFPFW_NW_SRC_SHIFT
    if w == ofp.OFPFW_NW_DST_MASK:
        return (x & ofp.OFPFW_NW_DST_MASK) >> ofp.OFPFW_NW_DST_SHIFT
    return 1 if (x & w) != 0 else 0


all_actions_list = [ofp.OFPAT_OUTPUT,
                    ofp.OFPAT_SET_VLAN_VID,
                    ofp.OFPAT_SET_VLAN_PCP,
                    ofp.OFPAT_STRIP_VLAN,
                    ofp.OFPAT_SET_DL_SRC,
                    ofp.OFPAT_SET_DL_DST,
                    ofp.OFPAT_SET_NW_SRC,
                    ofp.OFPAT_SET_NW_DST,
                    ofp.OFPAT_SET_NW_TOS,
                    ofp.OFPAT_SET_TP_SRC,
                    ofp.OFPAT_SET_TP_DST,
                    ofp.OFPAT_ENQUEUE
                    ]

def dl_addr_to_str(a):
    return "%x:%x:%x:%x:%x:%x" % tuple(a)

def ip_addr_to_str(a, n):
    if n is not None:
        a = a & ~((1 << (32 - n)) - 1)
    result = "%d.%d.%d.%d" % (a >> 24, \
                              (a >> 16) & 0xff, \
                              (a >> 8) & 0xff, \
                              a & 0xff \
                              )
    if n is not None:
        result = result + ("/%d" % (n))
    return result
    

class Flow_Cfg:
    # Members:
    # - match
    # - idle_timeout
    # - hard_timeout
    # - priority
    # - action_list

    def __init__(self):
        self.priority        = 0
        self.match           = parse.ofp_match()
        self.match.wildcards = ofp.OFPFW_ALL
        self.idle_timeout    = 0
        self.hard_timeout    = 0
        self.actions         = action_list.action_list()

    # {pri, match} is considered a flow key
    def key_equal(self, x):
        if self.priority != x.priority:
            return False
        # TBD - Should this logic be moved to ofp_match.__eq__()?
        if self.match.wildcards != x.match.wildcards:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_IN_PORT) == 0 \
           and self.match.in_port != x.match.in_port:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_DST) == 0 \
           and self.match.dl_dst != x.match.dl_dst:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_SRC) == 0 \
           and self.match.dl_src != x.match.dl_src:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_VLAN) == 0 \
           and self.match.dl_vlan != x.match.dl_vlan:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_VLAN_PCP) == 0 \
           and self.match.dl_vlan_pcp != x.match.dl_vlan_pcp:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_TYPE) == 0 \
           and self.match.dl_type != x.match.dl_type:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_NW_TOS) == 0 \
           and self.match.nw_tos != x.match.nw_tos:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_NW_PROTO) == 0 \
           and self.match.nw_proto != x.match.nw_proto:
            return False
        n = wildcard_get(self.match.wildcards, ofp.OFPFW_NW_SRC_MASK)
        if n < 32:
            m = ~((1 << n) - 1)
            if (self.match.nw_src & m) != (x.match.nw_src & m):
                return False
        n = wildcard_get(self.match.wildcards, ofp.OFPFW_NW_DST_MASK)
        if n < 32:
            m = ~((1 << n) - 1)
            if (self.match.nw_dst & m) != (x.match.nw_dst & m):
                return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_TP_SRC) == 0 \
               and self.match.tp_src != x.match.tp_src:
            return False
        if wildcard_get(self.match.wildcards, ofp.OFPFW_TP_DST) == 0 \
               and self.match.tp_dst != x.match.tp_dst:
            return False
        return True

    def non_key_equal(self, x):
        if self.cookie != x.cookie:
            return False
        if self.idle_timeout != x.idle_timeout:
            return False
        if self.hard_timeout != x.hard_timeout:
            return False
        if test_param_get(pa_config, "dut", "") == "argon":
            pa_logger.debug("Doing argon-style action comparison")
            # Compare actions lists as unordered, since Argon may re-order
            # action lists.
            # This is in apparent violation of the spec.
            aa = copy.deepcopy(x.actions.actions)
            for a in self.actions.actions:
                i = 0
                while i < len(aa):
                    if a == aa[i]:
                        break
                    i = i + 1
                if i < len(aa):
                    aa.pop(i)
                else:
                    return False
            return aa == []
        else:
            return self.actions == x.actions
        
    def key_str(self):
        result = "priority=%d" % self.priority
        # TBD - Would be nice if ofp_match.show() was better behaved
        # (no newlines), and more intuitive (things in hex where approprate), etc.
        result = result + (", wildcards=0x%x={" % (self.match.wildcards))
        sep = ""
        for w in all_wildcards_list:
            if (self.match.wildcards & w) == 0:
                continue
            if w == ofp.OFPFW_NW_SRC_MASK:
                n = wildcard_get(self.match.wildcards, w)
                if n > 0:
                    result = result + sep + ("OFPFW_NW_SRC(%d)" % (n))
            elif w == ofp.OFPFW_NW_DST_MASK:
                n = wildcard_get(self.match.wildcards, w)
                if n > 0:
                    result = result + sep + ("OFPFW_NW_DST(%d)" % (n))
            else:
                result = result + sep + all_wildcard_names[w]
            sep = ", "
        result = result +"}"
        if wildcard_get(self.match.wildcards, ofp.OFPFW_IN_PORT) == 0:
            result = result + (", in_port=%d" % (self.match.in_port))
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_DST) == 0:
            result = result + (", dl_dst=%s" \
                               % (dl_addr_to_str(self.match.dl_dst)) \
                               )
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_SRC) == 0:
            result = result + (", dl_src=%s" \
                               % (dl_addr_to_str(self.match.dl_src)) \
                               )
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_VLAN) == 0:
            result = result + (", dl_vlan=%d" % (self.match.dl_vlan))
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_VLAN_PCP) == 0:
            result = result + (", dl_vlan_pcp=%d" % (self.match.dl_vlan_pcp))
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_TYPE) == 0:
            result = result + (", dl_type=0x%x" % (self.match.dl_type))
        if wildcard_get(self.match.wildcards, ofp.OFPFW_NW_TOS) == 0:
            result = result + (", nw_tos=0x%x" % (self.match.nw_tos))
        if wildcard_get(self.match.wildcards, ofp.OFPFW_NW_PROTO) == 0:
            result = result + (", nw_proto=%d" % (self.match.nw_proto))
        n = wildcard_get(self.match.wildcards, ofp.OFPFW_NW_SRC_MASK)
        if n < 32:
            result = result + (", nw_src=%s" % \
                               (ip_addr_to_str(self.match.nw_src, 32 - n)) \
                               )
        n = wildcard_get(self.match.wildcards, ofp.OFPFW_NW_DST_MASK)
        if n < 32:
            result = result + (", nw_dst=%s" % \
                               (ip_addr_to_str(self.match.nw_dst, 32 - n)) \
                               )
        if wildcard_get(self.match.wildcards, ofp.OFPFW_TP_SRC) == 0:
            result = result + (", tp_src=%d" % self.match.tp_src)
        if wildcard_get(self.match.wildcards, ofp.OFPFW_TP_DST) == 0:
            result = result + (", tp_dst=%d" % self.match.tp_dst)
        return result

    def __eq__(self, x):
        return (self.key_equal(x) and self.non_key_equal(x))

    def __str__(self):
        result = self.key_str()
        result = result + (", cookie=%d" % self.cookie)
        result = result + (", idle_timeout=%d" % self.idle_timeout)
        result = result + (", hard_timeout=%d" % self.hard_timeout)
        for a in self.actions.actions:
            result = result + (", action=%s" % ofp.ofp_action_type_map[a.type])
            if a.type == ofp.OFPAT_OUTPUT:
                result = result + ("(%d)" % (a.port))
            elif a.type == ofp.OFPAT_SET_VLAN_VID:
                result = result + ("(%d)" % (a.vlan_vid))
            elif a.type == ofp.OFPAT_SET_VLAN_PCP:
                result = result + ("(%d)" % (a.vlan_pcp))
            elif a.type == ofp.OFPAT_SET_DL_SRC or a.type == ofp.OFPAT_SET_DL_DST:
                result = result + ("(%s)" % (dl_addr_to_str(a.dl_addr)))
            elif a.type == ofp.OFPAT_SET_NW_SRC or a.type == ofp.OFPAT_SET_NW_DST:
                result = result + ("(%s)" % (ip_addr_to_str(a.nw_addr, None)))
            elif a.type == ofp.OFPAT_SET_NW_TOS:
                result = result + ("(0x%x)" % (a.nw_tos))
            elif a.type == ofp.OFPAT_SET_TP_SRC or a.type == ofp.OFPAT_SET_TP_DST:
                result = result + ("(%d)" % (a.tp_port))
            elif a.type == ofp.OFPAT_ENQUEUE:
                result = result + ("(port=%d,queue=%d)" % (a.port, a.queue_id))
        return result

    def rand_actions_argon(self, fi, valid_actions, valid_ports):
        # Action lists are ordered, so pick an ordered random subset of
        # supported actions
        supported_actions = []
        for a in all_actions_list:
            if ((1 << a) & valid_actions) != 0:
                supported_actions.append(a)

        supported_actions = shuffle(supported_actions)
        supported_actions \
            = supported_actions[0 : random.randint(1, len(supported_actions))]

        # The setting of max_len to 65535 is a hack, since that's what's
        # returned by Argon for all actions (for now...)

        self.actions = action_list.action_list()
        for a in supported_actions:
            if a == ofp.OFPAT_OUTPUT:
                pass                    # OUTPUT actions must come last
            elif a == ofp.OFPAT_SET_VLAN_VID:
                act = action.action_set_vlan_vid()
                act.vlan_vid = fi.rand_vlan()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_VLAN_PCP:
                act = action.action_set_vlan_pcp()
                act.vlan_pcp = random.randint(0, (1 << 3) - 1)
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_STRIP_VLAN:
                act = action.action_strip_vlan()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_DL_SRC:
                act = action.action_set_dl_src()
                act.dl_addr = fi.rand_dl_addr()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_DL_DST:
                act = action.action_set_dl_dst()
                act.dl_addr = fi.rand_dl_addr()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_NW_SRC:
                act = action.action_set_nw_src()
                act.nw_addr = fi.rand_ip_addr()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_NW_DST:
                act = action.action_set_nw_dst()
                act.nw_addr = fi.rand_ip_addr()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_NW_TOS:
                act = action.action_set_nw_tos()
                act.nw_tos = fi.rand_ip_tos()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_TP_SRC:
                act = action.action_set_tp_src()
                act.tp_port = fi.rand_l4_port()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_TP_DST:
                act = action.action_set_tp_dst()
                act.tp_port = fi.rand_l4_port()
                act.max_len = 65535
                self.actions.add(act)
            elif a == ofp.OFPAT_ENQUEUE:
                pass                    # Enqueue actions must come last

        p = random.randint(1, 100)
        if p <= 33:
            # One third of the time, include ENQUEUE actions at end of list
            # At most 1 ENQUEUE action
            act = action.action_enqueue()
            act.port = rand_pick(valid_ports)
            # TBD - Limits for queue number?
            act.queue_id = random.randint(0, 7)
            act.max_len = 65535
            self.actions.add(act)
        elif p <= 66:
            # One third of the time, include OUTPUT actions at end of list
            port_idxs = shuffle(range(len(valid_ports)))
            # Only 1 output action allowed if IN_PORT wildcarded
            n = 1 if wildcard_get(self.match.wildcards, ofp.OFPFW_IN_PORT) != 0 \
                else random.randint(1, len(valid_ports))
            port_idxs = port_idxs[0 : n]
            for pi in port_idxs:
                act = action.action_output()
                act.port = valid_ports[pi]
                act.max_len = 65535
                if act.port != ofp.OFPP_IN_PORT \
                   or wildcard_get(self.match.wildcards, ofp.OFPFW_IN_PORT) == 0:
                    # OUTPUT(IN_PORT) only valid if OFPFW_IN_PORT not wildcarded
                    self.actions.add(act)
        else:
            # One third of the time, include neither
            pass


    # Randomize flow data for flow modifies (i.e. cookie and actions)
    def rand_mod(self, fi, valid_actions, valid_ports):
        self.cookie = random.randint(0, (1 << 53) - 1)

        if test_param_get(pa_config, "dut", "") == "argon":
            pa_logger.debug("Generating actions for argon")
            self.rand_actions_argon(fi, valid_actions, valid_ports)
            return self

        # Action lists are ordered, so pick an ordered random subset of
        # supported actions
        supported_actions = []
        for a in all_actions_list:
            if ((1 << a) & valid_actions) != 0:
                supported_actions.append(a)

        supported_actions = shuffle(supported_actions)
        supported_actions \
            = supported_actions[0 : random.randint(1, len(supported_actions))]

        self.actions = action_list.action_list()
        for a in supported_actions:
            if a == ofp.OFPAT_OUTPUT:
                # TBD - Output actions are clustered in list, spread them out?
                port_idxs = shuffle(range(len(valid_ports)))
                port_idxs = port_idxs[0 : random.randint(1, len(valid_ports))]
                for pi in port_idxs:
                    act = action.action_output()
                    act.port = valid_ports[pi]
                    self.actions.add(act)
            elif a == ofp.OFPAT_SET_VLAN_VID:
                act = action.action_set_vlan_vid()
                act.vlan_vid = fi.rand_vlan()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_VLAN_PCP:
                if test_param_get(pa_config, "dut", "") == "indigo":
                    pa_logger.debug("OFPAT_SET_VLAN_PCP broken on indigo")
                    pa_logger.debug("not using")
                    # Temporaily removed, broken in Indigo
                    pass
                else:
                    act = action.action_set_vlan_pcp()
                    act.vlan_pcp = random.randint(0, (1 << 3) - 1)
            elif a == ofp.OFPAT_STRIP_VLAN:
                act = action.action_strip_vlan()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_DL_SRC:
                act = action.action_set_dl_src()
                act.dl_addr = fi.rand_dl_addr()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_DL_DST:
                act = action.action_set_dl_dst()
                act.dl_addr = fi.rand_dl_addr()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_NW_SRC:
                act = action.action_set_nw_src()
                act.nw_addr = fi.rand_ip_addr()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_NW_DST:
                act = action.action_set_nw_dst()
                act.nw_addr = fi.rand_ip_addr()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_NW_TOS:
                act = action.action_set_nw_tos()
                act.nw_tos = fi.rand_ip_tos()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_TP_SRC:
                act = action.action_set_tp_src()
                act.tp_port = fi.rand_l4_port()
                self.actions.add(act)
            elif a == ofp.OFPAT_SET_TP_DST:
                act = action.action_set_tp_dst()
                act.tp_port = fi.rand_l4_port()
                self.actions.add(act)
            elif a == ofp.OFPAT_ENQUEUE:
                # TBD - Enqueue actions are clustered in list, spread them out?
                port_idxs = shuffle(range(len(valid_ports)))
                port_idxs = port_idxs[0 : random.randint(1, len(valid_ports))]
                for pi in port_idxs:
                    act = action.action_enqueue()
                    act.port = valid_ports[pi]
                    # TBD - Limits for queue number?
                    act.queue_id = random.randint(0, 7)
                    self.actions.add(act)

        return self

    # Randomize flow cfg
    def rand(self, fi, valid_wildcards, valid_actions, valid_ports):
        # Start with no wildcards, i.e. everything specified
        self.match.wildcards = 0
        
        # Make approx. 5% of flows exact
        exact = (random.randint(1, 100) <= 5)

        # For each qualifier Q,
        #   if (wildcarding is not supported for Q,
        #       or an exact flow is specified
        #       or a coin toss comes up heads), 
        #      specify Q
        #   else
        #      wildcard Q

        if wildcard_get(valid_wildcards, ofp.OFPFW_IN_PORT) == 0 \
           or exact \
           or flip_coin():
            self.match.in_port = rand_pick(valid_ports)
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_IN_PORT, \
                                                1 \
                                                )
            
        if wildcard_get(valid_wildcards, ofp.OFPFW_DL_DST) == 0 \
           or exact \
           or flip_coin():
            self.match.dl_dst = fi.rand_dl_addr()
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_DL_DST, \
                                                1 \
                                                )

        if wildcard_get(valid_wildcards, ofp.OFPFW_DL_SRC) == 0 \
           or exact \
           or flip_coin():
            self.match.dl_src = fi.rand_dl_addr()
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_DL_SRC, \
                                                1 \
                                                )

        if wildcard_get(valid_wildcards, ofp.OFPFW_DL_VLAN_PCP) == 0 \
           or exact \
           or flip_coin():
            self.match.dl_vlan_pcp = random.randint(0, (1 << 3) - 1)
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_DL_VLAN_PCP, \
                                                1 \
                                                )

        if wildcard_get(valid_wildcards, ofp.OFPFW_DL_VLAN) == 0 \
           or exact \
           or flip_coin():
            self.match.dl_vlan = fi.rand_vlan()
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_DL_VLAN, \
                                                1 \
                                                )

        if wildcard_get(valid_wildcards, ofp.OFPFW_DL_TYPE) == 0 \
           or exact \
           or flip_coin():
            self.match.dl_type = fi.rand_ethertype()
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_DL_TYPE, \
                                                1 \
                                                )

        if exact or flip_coin():
            n = 0
        else:
            n = wildcard_get(valid_wildcards, ofp.OFPFW_NW_SRC_MASK)
            if n > 32:
                n = 32
            n = random.randint(0, n)
        self.match.wildcards = wildcard_set(self.match.wildcards, \
                                            ofp.OFPFW_NW_SRC_MASK, \
                                            n \
                                            )
        if n < 32:
            self.match.nw_src    = fi.rand_ip_addr() & ~((1 << n) - 1)
            # Specifying any IP address match other than all bits
            # don't care requires that Ethertype is one of {IP, ARP}
            if flip_coin():
                self.match.dl_type   = rand_pick([0x0800, 0x0806])
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_DL_TYPE, \
                                                    0 \
                                                    )

        if exact or flip_coin():
            n = 0
        else:
            n = wildcard_get(valid_wildcards, ofp.OFPFW_NW_DST_MASK)
            if n > 32:
                n = 32
            n = random.randint(0, n)
        self.match.wildcards = wildcard_set(self.match.wildcards, \
                                            ofp.OFPFW_NW_DST_MASK, \
                                            n \
                                            )
        if n < 32:
            self.match.nw_dst    = fi.rand_ip_addr() & ~((1 << n) - 1)
            # Specifying any IP address match other than all bits
            # don't care requires that Ethertype is one of {IP, ARP}
            if flip_coin():
                self.match.dl_type   = rand_pick([0x0800, 0x0806])
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_DL_TYPE, \
                                                    0 \
                                                    )

        if wildcard_get(valid_wildcards, ofp.OFPFW_NW_TOS) == 0 \
           or exact \
           or flip_coin():
            self.match.nw_tos = fi.rand_ip_tos()
            # Specifying a TOS value requires that Ethertype is IP
            if flip_coin():
                self.match.dl_type   = 0x0800
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_DL_TYPE, \
                                                    0 \
                                                    )
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_NW_TOS, \
                                                1 \
                                                )

        if test_param_get(pa_config, "dut", "") == "ovs":
            pa_logger.debug("Flow canonicalization broken")
            pa_logger.debug("for OFPFW_NW_PROTO on ovs, always wildcarding")
            # Due to a bug in OVS, don't specify nw_proto on it's own.
            # OVS will allow specifying a value for nw_proto, even
            # if dl_type is not specified as IP.
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_NW_PROTO, \
                                                1 \
                                                )
        else:
            if wildcard_get(valid_wildcards, ofp.OFPFW_NW_PROTO) == 0 \
                   or exact \
                   or flip_coin():
                self.match.nw_proto = fi.rand_ip_proto()
                # Specifying an IP protocol requires that Ethertype is IP
                if flip_coin():
                    self.match.dl_type   = 0x0800
                    self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                        ofp.OFPFW_DL_TYPE, \
                                                        0 \
                                                        )
            else:            
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_NW_PROTO, \
                                                    1 \
                                                    )
            
        if wildcard_get(valid_wildcards, ofp.OFPFW_TP_SRC) == 0 \
           or exact\
           or flip_coin():
            self.match.tp_src = fi.rand_l4_port()
            # Specifying a L4 port requires that IP protcol is
            # one of {ICMP, TCP, UDP}
            if flip_coin():
                self.match.nw_proto = rand_pick([1, 6, 17])
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_NW_PROTO, \
                                                    0 \
                                                    )
                # Specifying a L4 port requirues that Ethertype is IP
                self.match.dl_type   = 0x0800
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_DL_TYPE, \
                                                    0 \
                                                    )
                if self.match.nw_proto == 1:
                    self.match.tp_src = self.match.tp_src & 0xff
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_TP_SRC, \
                                                1 \
                                                )

        if wildcard_get(valid_wildcards, ofp.OFPFW_TP_DST) == 0 \
           or exact \
           or flip_coin():
            self.match.tp_dst = fi.rand_l4_port()
            # Specifying a L4 port requires that IP protcol is
            # one of {ICMP, TCP, UDP}
            if flip_coin():
                self.match.nw_proto = rand_pick([1, 6, 17])
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_NW_PROTO, \
                                                    0 \
                                                    )
                # Specifying a L4 port requirues that Ethertype is IP
                self.match.dl_type   = 0x0800
                self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                    ofp.OFPFW_DL_TYPE, \
                                                    0 \
                                                    )
                if self.match.nw_proto == 1:
                    self.match.tp_dst = self.match.tp_dst & 0xff
        else:
            self.match.wildcards = wildcard_set(self.match.wildcards, \
                                                ofp.OFPFW_TP_DST, \
                                                1 \
                                                )

        # If nothing is wildcarded, it is an exact flow spec -- some switches
        # (Open vSwitch, for one) *require* that exact flow specs
        # have priority 65535.
        self.priority = 65535 if self.match.wildcards == 0 \
                        else fi.rand_priority()

        # N.B. Don't make the timeout too short, else the flow might
        # disappear before we get a chance to check for it.
        t = random.randint(0, 65535)
        self.idle_timeout = 0 if t < 60 else t
        t = random.randint(0, 65535)
        self.hard_timeout = 0 if t < 60 else t

        self.rand_mod(fi, valid_actions, valid_ports)

        return self

    # Return flow cfg in canonical form
    # - There are dependencies between flow qualifiers, e.g. it only makes
    #   sense to qualify nw_proto if dl_type is qualified to be 0x0800 (IP).
    #   The canonical form of flow match criteria will "wildcard out"
    #   all such cases.
    def canonical(self):
        result = copy.deepcopy(self)
        if wildcard_get(result.match.wildcards, ofp.OFPFW_DL_TYPE) != 0 \
               or result.match.dl_type not in [0x0800, 0x0806]:
            # dl_tyoe is wildcarded, or specified as something other
            # than IP or ARP
            # => nw_src and nw_dst cannot be specified, must be wildcarded
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_NW_SRC_MASK, \
                                                  32 \
                                                  )
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_NW_DST_MASK, \
                                                  32 \
                                                  )
        if wildcard_get(result.match.wildcards, ofp.OFPFW_DL_TYPE) != 0 \
               or result.match.dl_type != 0x0800:
            # dl_type is wildcarded, or specified as something other than IP
            # => nw_proto, nw_tos, tp_src and tp_dst cannot be specified,
            #    must be wildcarded
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_NW_PROTO, \
                                                  1 \
                                                  )
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_NW_TOS, \
                                                  1 \
                                                  )
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_TP_SRC, \
                                                  1 \
                                                  )
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_TP_DST, \
                                                  1 \
                                                  )
        if wildcard_get(result.match.wildcards, ofp.OFPFW_NW_PROTO) != 0 \
               or result.match.nw_proto not in [1, 6, 17]:
            # nw_proto is wildcarded, or specified as something other than ICMP,
            # TCP or UDP
            # => tp_src and tp_dst cannot be specified, must be wildcarded
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_TP_SRC, \
                                                  1 \
                                                  )
            result.match.wildcards = wildcard_set(result.match.wildcards, \
                                                  ofp.OFPFW_TP_DST, \
                                                  1 \
                                                  )
        return result

    # Overlap check
    # delf == True <=> Check for delete overlap, else add overlap
    # "Add overlap" is defined as there exists a packet that could match both the
    # receiver and argument flowspecs
    # "Delete overlap" is defined as the specificity of the argument flowspec
    # is greater than or equal to the specificity of the receiver flowspec
    def overlaps(self, x, delf):
        if wildcard_get(self.match.wildcards, ofp.OFPFW_IN_PORT) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_IN_PORT) == 0:
                if self.match.in_port != x.match.in_port:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_VLAN) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_DL_VLAN) == 0:
                if self.match.dl_vlan != x.match.dl_vlan:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_SRC) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_DL_SRC) == 0:
                if self.match.dl_src != x.match.dl_src:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_DST) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_DL_DST) == 0:
                if self.match.dl_dst != x.match.dl_dst:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_TYPE) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_DL_TYPE) == 0:
                if self.match.dl_type != x.match.dl_type:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Recevier more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_NW_PROTO) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_NW_PROTO) == 0:
                if self.match.nw_proto != x.match.nw_proto:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_TP_SRC) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_TP_SRC) == 0:
                if self.match.tp_src != x.match.tp_src:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_TP_DST) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_TP_DST) == 0:
                if self.match.tp_dst != x.match.tp_dst:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        na = wildcard_get(self.match.wildcards, ofp.OFPFW_NW_SRC_MASK)
        nb = wildcard_get(x.match.wildcards, ofp.OFPFW_NW_SRC_MASK)
        if delf and na < nb:
            return False                # Receiver more specific
        if (na < 32 and nb < 32):
            m = ~((1 << na) - 1) & ~((1 << nb) - 1)
            if (self.match.nw_src & m) != (x.match.nw_src & m):
                return False            # Overlapping bits not equal
        na = wildcard_get(self.match.wildcards, ofp.OFPFW_NW_DST_MASK)
        nb = wildcard_get(x.match.wildcards, ofp.OFPFW_NW_DST_MASK)
        if delf and na < nb:
            return False                # Receiver more specific
        if (na < 32 and nb < 32):
            m = ~((1 << na) - 1) & ~((1 << nb) - 1)
            if (self.match.nw_dst & m) != (x.match.nw_dst & m):
                return False            # Overlapping bits not equal
        if wildcard_get(self.match.wildcards, ofp.OFPFW_DL_VLAN_PCP) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_DL_VLAN_PCP) == 0:
                if self.match.dl_vlan_pcp != x.match.dl_vlan_pcp:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        if wildcard_get(self.match.wildcards, ofp.OFPFW_NW_TOS) == 0:
            if wildcard_get(x.match.wildcards, ofp.OFPFW_NW_TOS) == 0:
                if self.match.nw_tos != x.match.nw_tos:
                    return False        # Both specified, and not equal
            elif delf:
                return False            # Receiver more specific
        return True                     # Flows overlap

    def to_flow_mod_msg(self, msg):
        msg.match        = self.match
        msg.cookie       = self.cookie
        msg.idle_timeout = self.idle_timeout
        msg.hard_timeout = self.hard_timeout
        msg.priority     = self.priority
        msg.actions      = self.actions
        return msg

    def from_flow_stat(self, msg):
        self.match        = msg.match
        self.cookie       = msg.cookie
        self.idle_timeout = msg.idle_timeout
        self.hard_timeout = msg.hard_timeout
        self.priority     = msg.priority
        self.actions      = msg.actions

    def from_flow_rem(self, msg):
        self.match        = msg.match
        self.idle_timeout = msg.idle_timeout
        self.priority     = msg.priority


class Flow_Tbl:
    def clear(self):
        self.dict = {}

    def __init__(self):
        self.clear()

    def find(self, f):
        return self.dict.get(f.key_str(), None)

    def insert(self, f):
        self.dict[f.key_str()] = f

    def delete(self, f):
        del self.dict[f.key_str()]

    def values(self):
        return self.dict.values()

    def count(self):
        return len(self.dict)

    def rand(self, sw, fi, num_flows):
        self.clear()
        i = 0
        tbl = 0
        j = 0
        while i < num_flows:
            fc = Flow_Cfg()
            fc.rand(fi, \
                    sw.tbl_stats.stats[tbl].wildcards, \
                    sw.sw_features.actions, \
                    sw.valid_ports \
                    )
            fc = fc.canonical()
            if self.find(fc):
                continue
            fc.send_rem = False
            self.insert(fc)
            i = i + 1
            j = j + 1
            if j >= sw.tbl_stats.stats[tbl].max_entries:
                tbl = tbl + 1
                j = 0


error_msgs   = []
removed_msgs = []

def error_handler(self, msg, rawmsg):
    pa_logger.debug("Got an ERROR message, type=%d, code=%d" \
                    % (msg.type, msg.code) \
                    )
    global error_msgs
    error_msgs.append(msg)
    pass

def removed_handler(self, msg, rawmsg):
    pa_logger.debug("Got a REMOVED message")
    global removed_msgs
    removed_msgs.append(msg)
    pass

class Switch:
    # Members:
    # controller  - switch's test controller
    # sw_features - switch's OFPT_FEATURES_REPLY message
    # valid_ports - list of valid port numbers
    # tbl_stats   - switch's OFPT_STATS_REPLY message, for table stats request
    # flow_stats  - switch's OFPT_STATS_REPLY message, for flow stats request
    # flow_tbl    - (test's idea of) switch's flow table

    def __init__(self):
        self.controller  = None
        self.sw_features = None
        self.valid_ports = []
        self.tbl_stats   = None
        self.flow_stats  = None
        self.flow_tbl    = Flow_Tbl()

    def controller_set(self, controller):
        self.controller = controller
        # Register error message handler
        global error_msgs
        error_msgs = []
        controller.register(ofp.OFPT_ERROR, error_handler)
        controller.register(ofp.OFPT_FLOW_REMOVED, removed_handler)

    def features_get(self):
        # Get switch features
        request = message.features_request()
        (self.sw_features, pkt) = self.controller.transact(request, timeout=2)
        if self.sw_features is None:
            return False
        self.valid_ports = map(lambda x: x.port_no, self.sw_features.ports)
        # TBD - OFPP_LOCAL is returned by OVS is switch features --
        # is that universal?

        # TBD - There seems to be variability in which switches support which
        # ports; need to sort that out
        # TBD - Is it legal to enqueue to a special port?  Depends on switch?
#         self.valid_ports.extend([ofp.OFPP_IN_PORT, \
#                                  ofp.OFPP_NORMAL, \
#                                  ofp.OFPP_FLOOD, \
#                                  ofp.OFPP_ALL, \
#                                  ofp.OFPP_CONTROLLER \
#                                  ] \
#                                 )
        return True

    def tbl_stats_get(self):
        # Get table stats
        request = message.table_stats_request()
        (self.tbl_stats, pkt) = self.controller.transact(request, timeout=2)
        return (self.tbl_stats is not None)

    def flow_stats_get(self):
        request = message.flow_stats_request()
        query_match           = ofp.ofp_match()
        query_match.wildcards = ofp.OFPFW_ALL
        request.match    = query_match
        request.table_id = 0xff
        request.out_port = ofp.OFPP_NONE;
        if self.controller.message_send(request) == -1:
            return False
        # <TBD>
        # Glue together successive reponse messages for stats reply.
        # Looking at the "more" flag and performing re-assembly
        # should be a part of the infrastructure.
        # </TBD>
        n = 0
        while True:
            # TBD - Check for "more" flag
            (resp, pkt) = self.controller.poll(ofp.OFPT_STATS_REPLY, 1)
            if resp is None:
                break
            if n == 0:
                self.flow_stats = resp
            else:
                self.flow_stats.stats.extend(resp.stats)
            n = n + 1
        return (n > 0)

    def flow_add(self, flow_cfg, overlapf = False):
        flow_mod_msg = message.flow_mod()
        flow_mod_msg.command     = ofp.OFPFC_ADD
        flow_mod_msg.buffer_id   = 0xffffffff
        flow_cfg.to_flow_mod_msg(flow_mod_msg)
        if overlapf:
            flow_mod_msg.flags = flow_mod_msg.flags | ofp.OFPFF_CHECK_OVERLAP
        if flow_cfg.send_rem:
            flow_mod_msg.flags = flow_mod_msg.flags | ofp.OFPFF_SEND_FLOW_REM
        return (self.controller.message_send(flow_mod_msg) != -1)

    def flow_mod(self, flow_cfg, strictf):
        flow_mod_msg = message.flow_mod()
        flow_mod_msg.command     = ofp.OFPFC_MODIFY_STRICT if strictf \
                                   else ofp.OFPFC_MODIFY
        flow_mod_msg.buffer_id   = 0xffffffff
        flow_cfg.to_flow_mod_msg(flow_mod_msg)
        return (self.controller.message_send(flow_mod_msg) != -1)

    def flow_del(self, flow_cfg, strictf):
        flow_mod_msg = message.flow_mod()
        flow_mod_msg.command     = ofp.OFPFC_DELETE_STRICT if strictf \
                                   else ofp.OFPFC_DELETE
        flow_mod_msg.buffer_id   = 0xffffffff
        # TBD - "out_port" filtering of deletes needs to be tested
        flow_mod_msg.out_port    = ofp.OFPP_NONE
        flow_cfg.to_flow_mod_msg(flow_mod_msg)
        return (self.controller.message_send(flow_mod_msg) != -1)

    def barrier(self):
        barrier = message.barrier_request()
        (resp, pkt) = self.controller.transact(barrier, 5)
        return (resp is not None)

    def errors_verify(self, num_exp, type = 0, code = 0):
        result = True
        global error_msgs
        pa_logger.debug("Expecting %d error messages" % (num_exp))
        num_got = len(error_msgs)
        pa_logger.debug("Got %d error messages" % (num_got))
        if num_got != num_exp:
            pa_logger.error("Incorrect number of error messages received")
            result = False
        if num_exp == 0:
            return result
        elif num_exp == 1:
            pa_logger.debug("Expecting error message, type=%d, code=%d" \
                            % (type, code) \
                            )
            f = False
            for e in error_msgs:
                if e.type == type and e.code == code:
                    pa_logger.debug("Got it")
                    f = True
            if not f:
                pa_logger.error("Did not get it")
                result = False
        else:
            pa_logger.error("Can't expect more than 1 error message type")
            result = False
        return result

    def removed_verify(self, num_exp):
        result = True
        global removed_msgs
        pa_logger.debug("Expecting %d removed messages" % (num_exp))
        num_got = len(removed_msgs)
        pa_logger.debug("Got %d removed messages" % (num_got))
        if num_got != num_exp:
            pa_logger.error("Incorrect number of removed messages received")
            result = False
        if num_exp < 2:
            return result
        pa_logger.error("Can't expect more than 1 error message type")
        return False

        
#         pa_logger.debug("Expecting %d error messages" % (num))
#         if num > 0:
#             pa_logger.debug("with type=%d code=%d" % (type, code))            
#         result = True
#         n = 0
#         while True:
#             (errmsg, pkt) = self.controller.poll(ofp.OFPT_ERROR, 1)
#             if errmsg is None:
#                 break
#             pa_logger.debug("Got error message, type=%d, code=%d" \
#                               % (errmsg.type, errmsg.code) \
#                               )
#             if num == 0 or errmsg.type != type or errmsg.code != code:
#                 pa_logger.debug("Unexpected error message")
#                 result = False
#             n = n + 1
#         if n != num:
#             pa_logger.error("Received %d error messages" % (n))
#             result = False
#         return result

    def flow_tbl_verify(self):
        result = True
    
        # Verify flow count in switch
        pa_logger.debug("Reading table stats")
        pa_logger.debug("Expecting %d flows" % (self.flow_tbl.count()))
        if not self.tbl_stats_get():
            pa_logger.error("Get table stats failed")
            return False
        n = 0
        for ts in self.tbl_stats.stats:
            n = n + ts.active_count
        pa_logger.debug("Table stats reported %d active flows" \
                          % (n) \
                          )
        if n != self.flow_tbl.count():
            pa_logger.error("Incorrect number of active flows reported")
            result = False
    
        # Read flows from switch
        pa_logger.debug("Retrieving flows from switch")
        pa_logger.debug("Expecting %d flows" % (self.flow_tbl.count()))
        if not self.flow_stats_get():
            pa_logger.error("Get flow stats failed")
            return False
        pa_logger.debug("Retrieved %d flows" % (len(self.flow_stats.stats)))
    
        # Verify flows returned by switch
    
        if len(self.flow_stats.stats) != self.flow_tbl.count():
            pa_logger.error("Switch reported incorrect number of flows")
            result = False
    
        pa_logger.debug("Verifying received flows")
        for fc in self.flow_tbl.values():
            fc.matched = False
        for fs in self.flow_stats.stats:
            flow_in = Flow_Cfg()
            flow_in.from_flow_stat(fs)
            pa_logger.debug("Received flow:")
            pa_logger.debug(str(flow_in))
            fc = self.flow_tbl.find(flow_in)
            if fc is None:
                pa_logger.error("does not match any defined flow")
                result = False
            elif fc.matched:
                pa_logger.error("re-matches defined flow:")
                pa_logger.debug(str(fc))
                result = False
            else:
                pa_logger.debug("matched")
                if not flow_in == fc:
                    pa_logger.error("Non-key portions of flow do not match")
                    result = False
                fc.matched = True
        for fc in self.flow_tbl.values():
            if not fc.matched:
                pa_logger.error("Defined flow:")
                pa_logger.error(str(fc))
                pa_logger.error("was not returned by switch")
                result = False
    
        return result


class Flow_Add_5(basic.SimpleProtocol):
    """
    Test FLOW_ADD_5 from draft top-half test plan
    
    INPUTS
    num_flows - Number of flows to generate
    """

    def runTest(self):
        pa_logger.debug("Flow_Add_5 TEST BEGIN")

        num_flows = test_param_get(pa_config, "num_flows", 100)

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        if num_flows == 0:
            # Number of flows requested was 0
            # => Generate max number of flows

            for ts in sw.tbl_stats.stats:
                num_flows = num_flows + ts.max_entries

        pa_logger.debug("Generating %d flows" % (num_flows))        

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(2 * int(math.log(num_flows)))

        # Create a flow table

        ft = Flow_Tbl()
        ft.rand(sw, fi, num_flows)

        # Send flow table to switch

        pa_logger.debug("Sending flow adds to switch")
        for fc in ft.values():          # Randomizes order of sending
            pa_logger.debug("Adding flow:")
            pa_logger.debug(str(fc));
            self.assertTrue(sw.flow_add(fc), "Failed to add flow")

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Add_5 TEST FAILED")
        pa_logger.debug("Flow_Add_5 TEST PASSED")


class Flow_Add_5_1(basic.SimpleProtocol):
    """
    Test FLOW_ADD_5.1 from draft top-half test plan

    INPUTS
    None
    """
    
    def runTest(self):
        pa_logger.debug("Flow_Add_5_1 TEST BEGIN")

        num_flows = test_param_get(pa_config, "num_flows", 100)
        
        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config that will be canonicalized by the switch

        while True:
            fc = Flow_Cfg()
            fc.rand(fi, \
                    sw.tbl_stats.stats[0].wildcards, \
                    sw.sw_features.actions, \
                    sw.valid_ports \
                    )
            fcc = fc.canonical()
            if fcc != fc:
                break

        ft = Flow_Tbl()
        ft.insert(fcc)

        # Send it to the switch

        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc))
        pa_logger.debug("should be canonicalized as:")
        pa_logger.debug(str(fcc))
        fc.send_rem = False
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Add_5_1 TEST FAILED")
        pa_logger.debug("Flow_Add_5_1 TEST PASSED")


# Disabled because of bogus capacity reported by OVS.
# Should be DUT dependent.
test_prio["Flow_Add_6"] = -1

class Flow_Add_6(basic.SimpleProtocol):
    """
    Test FLOW_ADD_6 from draft top-half test plan
    
    INPUTS
    num_flows - Number of flows to generate
    """

    def runTest(self):
        pa_logger.debug("Flow_Add_6 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        num_flows = 0
        for ts in sw.tbl_stats.stats:
            num_flows = num_flows + ts.max_entries

        pa_logger.debug("Switch capacity is %d flows" % (num_flows))        
        pa_logger.debug("Generating %d flows" % (num_flows))        

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(2 * int(math.log(num_flows)))

        # Create a flow table, to switch's capacity

        ft = Flow_Tbl()
        ft.rand(sw, fi, num_flows)

        # Send flow table to switch

        pa_logger.debug("Sending flow adds to switch")
        for fc in ft.values():          # Randomizes order of sending
            pa_logger.debug("Adding flow:")
            pa_logger.debug(str(fc));
            self.assertTrue(sw.flow_add(fc), "Failed to add flow")

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Dream up one more flow

        pa_logger.debug("Creating one more flow")
        while True:
            fc = Flow_Cfg()
            fc.rand(fi, \
                    sw.tbl_stats.stats[tbl].wildcards, \
                    sw.sw_features.actions, \
                    sw.valid_ports \
                    )
            fc = fc.canonical()
            if ft.find(fc):
                continue

        # Send one-more flow

        fc.send_rem = False
        pa_logger.debug("Sending flow add switch")
        pa_logger.debug(str(fc));
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        # Check for expected error message

        if not sw.errors_verify(1, \
                                ofp.OFPET_FLOW_MOD_FAILED, \
                                ofp.OFPFMFC_ALL_TABLES_FULL \
                                ):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_add_6 TEST FAILED")
        pa_logger.debug("Flow_add_6 TEST PASSED")


class Flow_Add_7(basic.SimpleProtocol):
    """
    Test FLOW_ADD_7 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Add_7 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config

        fc = Flow_Cfg()
        fc.rand(fi, \
                sw.tbl_stats.stats[0].wildcards, \
                sw.sw_features.actions, \
                sw.valid_ports \
                )
        fc = fc.canonical()

        # Send it to the switch

        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc))
        ft = Flow_Tbl()
        fc.send_rem = False
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")
        ft.insert(fc)

        # Dream up some different actions, with the same flow key

        fc2 = copy.deepcopy(fc)
        while True:
            fc2.rand_mod(fi, \
                         sw.sw_features.actions, \
                         sw.valid_ports \
                         )
            if fc2 != fc:
                break

        # Send that to the switch
        
        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc2))
        fc2.send_rem = False
        self.assertTrue(sw.flow_add(fc2), "Failed to add flow")
        ft.insert(fc2)

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Add_7 TEST FAILED")
        pa_logger.debug("Flow_Add_7 TEST PASSED")


class Flow_Add_8(basic.SimpleProtocol):
    """
    Test FLOW_ADD_8 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Add_8 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config, with at least 1 qualifier specified

        fc = Flow_Cfg()
        while True:
            fc.rand(fi, \
                    sw.tbl_stats.stats[0].wildcards, \
                    sw.sw_features.actions, \
                    sw.valid_ports \
                    )
            fc = fc.canonical()
            if fc.match.wildcards != ofp.OFPFW_ALL:
                break

        # Send it to the switch

        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc))
        ft = Flow_Tbl()
        fc.send_rem = False
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")
        ft.insert(fc)

        # Wildcard out one qualifier that was specified, to create an
        # overlapping flow

        fc2 = copy.deepcopy(fc)
        for wi in shuffle(range(len(all_wildcards_list))):
            w = all_wildcards_list[wi]
            if (fc2.match.wildcards & w) == 0:
                break
        if w == ofp.OFPFW_NW_SRC_MASK:
            w  = ofp.OFPFW_NW_SRC_ALL
            wn = "OFPFW_NW_SRC"
        elif w == ofp.OFPFW_NW_DST_MASK:
            w  = ofp.OFPFW_NW_DST_ALL
            wn = "OFPFW_NW_DST"
        else:
            wn = all_wildcard_names[w]
        pa_logger.debug("Wildcarding out %s" % (wn))
        fc2.match.wildcards = fc2.match.wildcards | w

        # Send that to the switch, with overlap checking
        
        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc2))
        fc2.send_rem = False
        self.assertTrue(sw.flow_add(fc2, True), "Failed to add flow")

        # Do barrier, to make sure all flows are in
        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for expected error message

        if not sw.errors_verify(1, \
                                ofp.OFPET_FLOW_MOD_FAILED, \
                                ofp.OFPFMFC_OVERLAP \
                                ):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Add_8 TEST FAILED")
        pa_logger.debug("Flow_Add_8 TEST PASSED")


class Flow_Mod_1(basic.SimpleProtocol):
    """
    Test FLOW_MOD_1 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Mod_1 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config

        fc = Flow_Cfg()
        fc.rand(fi, \
                sw.tbl_stats.stats[0].wildcards, \
                sw.sw_features.actions, \
                sw.valid_ports \
                )
        fc = fc.canonical()

        # Send it to the switch

        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc))
        ft = Flow_Tbl()
        fc.send_rem = False
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")
        ft.insert(fc)

        # Dream up some different actions, with the same flow key

        fc2 = copy.deepcopy(fc)
        while True:
            fc2.rand_mod(fi, \
                         sw.sw_features.actions, \
                         sw.valid_ports \
                         )
            if fc2 != fc:
                break

        # Send that to the switch
        
        pa_logger.debug("Sending strict flow mod to switch:")
        pa_logger.debug(str(fc2))
        fc2.send_rem = False
        self.assertTrue(sw.flow_mod(fc2, True), "Failed to modify flow")
        ft.insert(fc2)

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Mod_1 TEST FAILED")
        pa_logger.debug("Flow_Mod_1 TEST PASSED")

        
class Flow_Mod_2(basic.SimpleProtocol):
    """
    Test FLOW_MOD_2 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Mod_2 TEST BEGIN")

        num_flows = test_param_get(pa_config, "num_flows", 100)

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        # Shrunk, to increase chance of meta-matches
        fi.rand(int(math.log(num_flows)) / 2)
        
        # Dream up some flows

        ft = Flow_Tbl()
        ft.rand(sw, fi, num_flows)

        # Send flow table to switch

        pa_logger.debug("Sending flow adds to switch")
        for fc in ft.values():          # Randomizes order of sending
            pa_logger.debug("Adding flow:")
            pa_logger.debug(str(fc));
            self.assertTrue(sw.flow_add(fc), "Failed to add flow")

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        # Pick a random flow as a basis
        
        mfc = copy.deepcopy(ft.values()[0])
        mfc.rand_mod(fi, sw.sw_features.actions, sw.valid_ports)

        # Repeatedly wildcard qualifiers

        for wi in shuffle(range(len(all_wildcards_list))):
            w = all_wildcards_list[wi]
            if w == ofp.OFPFW_NW_SRC_MASK or w == ofp.OFPFW_NW_DST_MASK:
                n = wildcard_get(mfc.match.wildcards, w)
                if n < 32:
                    mfc.match.wildcards = wildcard_set(mfc.match.wildcards, \
                                                       w, \
                                                       random.randint(n + 1, 32) \
                                                       )
                else:
                    continue
            else:
                if wildcard_get(mfc.match.wildcards, w) == 0:
                    mfc.match.wildcards = wildcard_set(mfc.match.wildcards, w, 1)
                else:
                    continue
            mfc = mfc.canonical()

            # Count the number of flows that would be modified

            n = 0
            for fc in ft.values():
                if mfc.overlaps(fc, True) and not mfc.non_key_equal(fc):
                    n = n + 1

            # If more than 1, we found our loose delete flow spec
            if n > 1:
                break
                    
        pa_logger.debug("Modifying %d flows" % (n))
        pa_logger.debug("Sending flow mod to switch:")
        pa_logger.debug(str(mfc))
        self.assertTrue(sw.flow_mod(mfc, False), "Failed to modify flow")

        # Do barrier, to make sure all flows are in
        self.assertTrue(sw.barrier(), "Barrier failed")

        # Check for error message

        if not sw.errors_verify(0):
            result = False

        # Apply flow mod to local flow table

        for fc in ft.values():
            if mfc.overlaps(fc, True):
                fc.cookie  = mfc.cookie
                fc.actions = mfc.actions

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Mod_2 TEST FAILED")
        pa_logger.debug("Flow_Mod_2 TEST PASSED")


class Flow_Mod_3(basic.SimpleProtocol):
    """
    Test FLOW_MOD_3 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Mod_3 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config

        fc = Flow_Cfg()
        fc.rand(fi, \
                sw.tbl_stats.stats[0].wildcards, \
                sw.sw_features.actions, \
                sw.valid_ports \
                )
        fc = fc.canonical()

        # Send it to the switch

        pa_logger.debug("Sending flow mod to switch:")
        pa_logger.debug(str(fc))
        ft = Flow_Tbl()
        fc.send_rem = False
        self.assertTrue(sw.flow_mod(fc, True), "Failed to modify flows")
        ft.insert(fc)

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Mod_3 TEST FAILED")
        pa_logger.debug("Flow_Mod_3 TEST PASSED")


class Flow_Del_1(basic.SimpleProtocol):
    """
    Test FLOW_DEL_1 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Del_1 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config

        fc = Flow_Cfg()
        fc.rand(fi, \
                sw.tbl_stats.stats[0].wildcards, \
                sw.sw_features.actions, \
                sw.valid_ports \
                )
        fc = fc.canonical()

        # Send it to the switch

        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc))
        ft = Flow_Tbl()
        fc.send_rem = False
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")
        ft.insert(fc)

        # Dream up some different actions, with the same flow key

        fc2 = copy.deepcopy(fc)
        while True:
            fc2.rand_mod(fi, \
                         sw.sw_features.actions, \
                         sw.valid_ports \
                         )
            if fc2 != fc:
                break

        # Delete strictly
        
        pa_logger.debug("Sending strict flow del to switch:")
        pa_logger.debug(str(fc2))
        self.assertTrue(sw.flow_del(fc2, True), "Failed to delete flow")
        ft.delete(fc)

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Del_1 TEST FAILED")
        pa_logger.debug("Flow_Del_1 TEST PASSED")


class Flow_Del_2(basic.SimpleProtocol):
    """
    Test FLOW_DEL_2 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Del_2 TEST BEGIN")

        num_flows = test_param_get(pa_config, "num_flows", 100)

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        # Shrunk, to increase chance of meta-matches
        fi.rand(int(math.log(num_flows)) / 2)
        
        # Dream up some flows

        ft = Flow_Tbl()
        ft.rand(sw, fi, num_flows)

        # Send flow table to switch

        pa_logger.debug("Sending flow adds to switch")
        for fc in ft.values():          # Randomizes order of sending
            pa_logger.debug("Adding flow:")
            pa_logger.debug(str(fc));
            self.assertTrue(sw.flow_add(fc), "Failed to add flow")

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for any error messages

        if not sw.errors_verify(0):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        # Pick a random flow as a basis
        
        dfc = copy.deepcopy(ft.values()[0])
        dfc.rand_mod(fi, sw.sw_features.actions, sw.valid_ports)

        # Repeatedly wildcard qualifiers

        for wi in shuffle(range(len(all_wildcards_list))):
            w = all_wildcards_list[wi]
            if w == ofp.OFPFW_NW_SRC_MASK or w == ofp.OFPFW_NW_DST_MASK:
                n = wildcard_get(dfc.match.wildcards, w)
                if n < 32:
                    dfc.match.wildcards = wildcard_set(dfc.match.wildcards, \
                                                       w, \
                                                       random.randint(n + 1, 32) \
                                                       )
                else:
                    continue
            else:
                if wildcard_get(dfc.match.wildcards, w) == 0:
                    dfc.match.wildcards = wildcard_set(dfc.match.wildcards, w, 1)
                else:
                    continue
            dfc = dfc.canonical()

            # Count the number of flows that would be deleted

            n = 0
            for fc in ft.values():
                if dfc.overlaps(fc, True):
                    n = n + 1

            # If more than 1, we found our loose delete flow spec
            if n > 1:
                break
                    
        pa_logger.debug("Deleting %d flows" % (n))
        pa_logger.debug("Sending flow del to switch:")
        pa_logger.debug(str(dfc))
        self.assertTrue(sw.flow_del(dfc, False), "Failed to delete flows")

        # Do barrier, to make sure all flows are in
        self.assertTrue(sw.barrier(), "Barrier failed")

        # Check for error message

        if not sw.errors_verify(0):
            result = False

        # Apply flow mod to local flow table

        for fc in ft.values():
            if dfc.overlaps(fc, True):
                ft.delete(fc)

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Del_2 TEST FAILED")
        pa_logger.debug("Flow_Del_2 TEST PASSED")


class Flow_Del_4(basic.SimpleProtocol):
    """
    Test FLOW_DEL_4 from draft top-half test plan
    
    INPUTS
    None
    """

    def runTest(self):
        pa_logger.debug("Flow_Del_4 TEST BEGIN")

        # Clear all flows from switch

        pa_logger.debug("Deleting all flows from switch")
        rc = delete_all_flows(self.controller, pa_logger)
        self.assertEqual(rc, 0, "Failed to delete all flows")

        # Get switch capabilites

        pa_logger.debug("Getting switch capabilities")        
        sw = Switch()
        sw.controller_set(self.controller)
        self.assertTrue(sw.features_get(), "Get switch features failed")
        self.assertTrue(sw.tbl_stats_get(), "Get table stats failed")

        # Dream up some flow information, i.e. space to chose from for
        # random flow parameter generation

        fi = Flow_Info()
        fi.rand(10)
        
        # Dream up a flow config

        fc = Flow_Cfg()
        fc.rand(fi, \
                sw.tbl_stats.stats[0].wildcards, \
                sw.sw_features.actions, \
                sw.valid_ports \
                )
        fc = fc.canonical()

        # Send it to the switch. with "notify on removed"

        pa_logger.debug("Sending flow add to switch:")
        pa_logger.debug(str(fc))
        ft = Flow_Tbl()
        fc.send_rem = True
        self.assertTrue(sw.flow_add(fc), "Failed to add flow")
        ft.insert(fc)

        # Dream up some different actions, with the same flow key

        fc2 = copy.deepcopy(fc)
        while True:
            fc2.rand_mod(fi, \
                         sw.sw_features.actions, \
                         sw.valid_ports \
                         )
            if fc2 != fc:
                break

        # Delete strictly
        
        pa_logger.debug("Sending strict flow del to switch:")
        pa_logger.debug(str(fc2))
        self.assertTrue(sw.flow_del(fc2, True), "Failed to delete flow")
        ft.delete(fc)

        # Do barrier, to make sure all flows are in

        self.assertTrue(sw.barrier(), "Barrier failed")

        result = True

        # Check for expected "removed" message

        if not sw.errors_verify(0):
            result = False

        if not sw.removed_verify(1):
            result = False

        # Verify flow table

        sw.flow_tbl = ft
        if not sw.flow_tbl_verify():
            result = False

        self.assertTrue(result, "Flow_Del_4 TEST FAILED")
        pa_logger.debug("Flow_Del_4 TEST PASSED")
        
