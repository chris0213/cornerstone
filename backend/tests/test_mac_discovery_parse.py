"""mac_discovery 解析器单测：覆盖华为/思科/H3C 三厂商的 MAC 表与 ARP 表输出样例"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.mac_discovery import parse_mac_table, parse_arp_table, normalize_mac, intf_tail  # noqa: E402

# 华为 MAC 表
HW_MAC = """-------------------------------------------------------------------------------
MAC Address    VLAN/VSI                       Learned-From                   Type
-------------------------------------------------------------------------------
5489-98bc-3c41 1/-                            GE0/0/1                        dynamic
5489-98bc-3c42 100/-                          GE0/0/2                        dynamic
5489-98bc-0001 1/-                            GE0/0/1                        static
-------------------------------------------------------------------------------
Total items: 3"""

# 思科 MAC 表
CISCO_MAC = """          Mac Address Table
-------------------------------------------
Vlan    Mac Address       Type        Interfaces
-----    -----------       --------    ---------
  100    aabb.cc00.0100    DYNAMIC     Gi0/1
  200    aabb.cc00.0200    DYNAMIC     Te0/1
Total Mac Addresses for this criterion: 2"""

# H3C MAC 表
H3C_MAC = """MAC ADDR       VLAN ID   STATE          PORT INDEX                             AGING
00e0-fc00-0001 100       Learned        GE1/0/1                                Y
00e0-fc00-0002 1         Learned        GigabitEthernet1/0/2                   Y"""

# 华为 ARP 表
HW_ARP = """IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE
10.1.1.2        5489-98bc-3c41  10        DYNAMIC     GE0/0/1     --
10.1.1.3        5489-98bc-3c42            STATIC      GE0/0/2     --"""

# 思科 ARP 表（含 Age 列与 Incomplete 行）
CISCO_ARP = """Protocol  Address          Age (min)  Hardware Addr   Type   Interface
Internet  10.2.1.5         5          aabb.cc00.0100  ARPA   Vlan100
Internet  10.2.1.6         -          Incomplete      ARPA"""

# H3C ARP 表
H3C_ARP = """IP address      MAC address    VLAN/VSI    Interface         State Type/Atk-type
10.3.1.9        00e0-fc00-0001 100         GE1/0/1           10    D"""


def test_parse_mac_table_huawei():
    assert parse_mac_table(HW_MAC) == [
        {'mac': '548998bc3c41', 'port': 'GE0/0/1'},
        {'mac': '548998bc3c42', 'port': 'GE0/0/2'},
    ]  # static 表项被排除


def test_parse_mac_table_cisco():
    assert parse_mac_table(CISCO_MAC) == [
        {'mac': 'aabbcc000100', 'port': 'Gi0/1'},
        {'mac': 'aabbcc000200', 'port': 'Te0/1'},
    ]


def test_parse_mac_table_h3c():
    assert parse_mac_table(H3C_MAC) == [
        {'mac': '00e0fc000001', 'port': 'GE1/0/1'},
        {'mac': '00e0fc000002', 'port': 'GigabitEthernet1/0/2'},
    ]


def test_parse_arp_table_huawei():
    assert parse_arp_table(HW_ARP) == {
        '548998bc3c41': '10.1.1.2',
        '548998bc3c42': '10.1.1.3',
    }


def test_parse_arp_table_cisco():
    assert parse_arp_table(CISCO_ARP) == {'aabbcc000100': '10.2.1.5'}  # Incomplete 行被排除


def test_parse_arp_table_h3c():
    assert parse_arp_table(H3C_ARP) == {'00e0fc000001': '10.3.1.9'}


def test_normalize_mac():
    assert normalize_mac('AA:BB:CC:DD:EE:FF') == 'aabbccddeeff'
    assert normalize_mac('aabb.ccdd.eeff') == 'aabbccddeeff'
    assert normalize_mac('invalid') is None


def test_intf_tail():
    assert intf_tail('GigabitEthernet0/0/1') == '0/0/1'
    assert intf_tail('GE0/0/1') == '0/0/1'
    assert intf_tail('Eth-Trunk1') == '1'
