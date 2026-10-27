"""Independent offline test barrier; disallow any socket connection/bind."""
import sys


def deny_network(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.bind'):
        raise AssertionError('SYNTHETIC_NETWORK_FORBIDDEN')


sys.addaudithook(deny_network)

import pytest

@pytest.fixture
def sdk():
    from sdk_adapter import load_sdk
    return load_sdk()
