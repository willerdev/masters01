from app.connectors.local_mt5 import LocalMT5Connector
from app.connectors.metaapi import MetaApiConnector

_META = MetaApiConnector()
_LOCAL = LocalMT5Connector()


def connector_for(method: str):
    if method == "metaapi":
        return _META
    if method == "local_mt5":
        return _LOCAL
    return None
