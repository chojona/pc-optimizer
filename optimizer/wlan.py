"""Read-only Native Wi-Fi API. No localized netsh parsing or active radio scans."""
import ctypes as c
import os
import threading
import uuid

U32, U16, U8 = c.c_uint32, c.c_uint16, c.c_ubyte


class GUID(c.Structure):
    _fields_ = [('data', U8 * 16)]


class SSID(c.Structure):
    _fields_ = [('length', U32), ('data', U8 * 32)]


class Interface(c.Structure):
    _fields_ = [('guid', GUID), ('description', c.c_wchar * 256), ('state', U32)]


class Association(c.Structure):
    _fields_ = [('ssid', SSID), ('bss_type', U32), ('bssid', U8 * 6),
                ('phy', U32), ('phy_index', U32), ('signal', U32), ('rx', U32), ('tx', U32)]


class Connection(c.Structure):
    _fields_ = [('state', U32), ('mode', U32), ('profile', c.c_wchar * 256),
                ('association', Association), ('security', U32 * 4)]


class RateSet(c.Structure):
    _fields_ = [('length', U32), ('rates', U16 * 126)]


class BSS(c.Structure):
    _fields_ = [('ssid', SSID), ('phy_id', U32), ('bssid', U8 * 6), ('bss_type', U32),
                ('phy_type', U32), ('rssi', c.c_int32), ('quality', U32),
                ('in_reg_domain', U8), ('beacon', U16), ('timestamp', c.c_uint64),
                ('host_timestamp', c.c_uint64), ('capability', U16),
                ('frequency', U32), ('rates', RateSet), ('ie_offset', U32), ('ie_size', U32)]


def frequency_channel(khz):
    mhz = khz / 1000
    if mhz == 2484:
        return '2.4 GHz', 14
    if 2412 <= mhz <= 2472:
        return '2.4 GHz', int((mhz - 2407) / 5)
    if mhz == 5935:
        return '6 GHz', 2
    if 5955 <= mhz <= 7115:
        return '6 GHz', int((mhz - 5950) / 5)
    if 5000 <= mhz < 5925:
        return '5 GHz', int((mhz - 5000) / 5)
    return 'Unknown band', None


def ssid_text(value):
    return bytes(value.data[:min(value.length, 32)]).decode('utf-8', 'replace') or '(hidden)'


def mac(value):
    return ':'.join(f'{b:02x}' for b in value)


def read_wifi():
    """OS cached BSS observations; access-denied/location permission remains explicit."""
    if os.name != 'nt':
        return {'interfaces': [], 'error': 'Native Wi-Fi requires Windows'}
    api = c.WinDLL('wlanapi')
    handle, version = c.c_void_p(), U32()
    ptr = c.c_void_p
    api.WlanOpenHandle.argtypes = [U32, ptr, c.POINTER(U32), c.POINTER(ptr)]
    api.WlanEnumInterfaces.argtypes = [ptr, ptr, c.POINTER(ptr)]
    api.WlanQueryInterface.argtypes = [ptr, c.POINTER(GUID), U32, ptr,
                                     c.POINTER(U32), c.POINTER(ptr), ptr]
    api.WlanGetNetworkBssList.argtypes = [ptr, c.POINTER(GUID), ptr, U32, c.c_int, ptr, c.POINTER(ptr)]
    api.WlanFreeMemory.argtypes = [ptr]
    api.WlanCloseHandle.argtypes = [ptr, ptr]
    def checked(code):
        if code:
            raise OSError(code, 'Wi-Fi unavailable; check WLAN AutoConfig and Windows location permission')
    interfaces = []
    try:
        checked(api.WlanOpenHandle(2, None, c.byref(version), c.byref(handle)))
        listing = ptr()
        checked(api.WlanEnumInterfaces(handle, None, c.byref(listing)))
        try:
            count = min(c.cast(listing, c.POINTER(U32))[0], 256)
            for i in range(count):
                info = Interface.from_address(listing.value + 8 + i * c.sizeof(Interface))
                item = {'guid': str(uuid.UUID(bytes_le=bytes(info.guid.data))),
                        'description': info.description, 'state': info.state, 'nearby': []}
                data, size = ptr(), U32()
                code = api.WlanQueryInterface(handle, c.byref(info.guid), 7, None,
                                               c.byref(size), c.byref(data), None)
                if not code:
                    try:
                        if size.value >= c.sizeof(Connection):
                            a = Connection.from_address(data.value).association
                            item.update(ssid=ssid_text(a.ssid), bssid=mac(a.bssid),
                                        signal_percent=a.signal, rx_mbps=a.rx / 1000, tx_mbps=a.tx / 1000)
                    finally:
                        api.WlanFreeMemory(data)
                elif info.state == 1:
                    item['connection_error'] = f'WLAN query error {code}; location permission may be required'
                data = ptr()
                code = api.WlanGetNetworkBssList(handle, c.byref(info.guid), None, 3, False, None, c.byref(data))
                if not code:
                    try:
                        total, n = c.cast(data, c.POINTER(U32))[:2]
                        for j in range(min(n, max(0, (total - 8) // c.sizeof(BSS)))):
                            b = BSS.from_address(data.value + 8 + j * c.sizeof(BSS))
                            band, channel = frequency_channel(b.frequency)
                            row = dict(ssid=ssid_text(b.ssid), bssid=mac(b.bssid), rssi_dbm=b.rssi,
                                       signal_percent=b.quality, frequency_khz=b.frequency,
                                       band=band, channel=channel, host_timestamp=b.host_timestamp)
                            item['nearby'].append(row)
                            if row['bssid'] == item.get('bssid'):
                                item.update(band=band, channel=channel, frequency_khz=b.frequency,
                                            rssi_dbm=b.rssi)
                    finally:
                        api.WlanFreeMemory(data)
                else:
                    item['bss_error'] = f'BSS error {code}; cached observations unavailable (check location permission)'
                interfaces.append(item)
        finally:
            api.WlanFreeMemory(listing)
        return {'interfaces': interfaces, 'source': 'Native WLAN API; OS cached observations, no active scan'}
    except OSError as exc:
        return {'interfaces': interfaces, 'error': str(exc)}
    finally:
        if handle.value:
            api.WlanCloseHandle(handle, None)


def scan_wifi(adapter_guid, *, approved=False):
    """User-initiated survey with ACM completion notification and a bounded wait.

    Scanning may briefly raise latency; never schedule this automatically.
    """
    if not approved:
        raise PermissionError('Explicit approval required: a radio survey may increase latency')
    identity = uuid.UUID(str(adapter_guid).strip('{}'))
    if os.name != 'nt':
        raise OSError('Native Wi-Fi requires Windows')
    class Notification(c.Structure):
        _fields_ = [('source', U32), ('code', U32), ('guid', GUID), ('size', U32), ('data', c.c_void_p)]
    callback_type = c.WINFUNCTYPE(None, c.POINTER(Notification), c.c_void_p)
    api = c.WinDLL('wlanapi')
    ptr = c.c_void_p
    api.WlanOpenHandle.argtypes = [U32, ptr, c.POINTER(U32), c.POINTER(ptr)]
    api.WlanScan.argtypes = [ptr, c.POINTER(GUID), ptr, ptr, ptr]
    api.WlanRegisterNotification.argtypes = [ptr, U32, c.c_int, callback_type, ptr, ptr, c.POINTER(U32)]
    api.WlanCloseHandle.argtypes = [ptr, ptr]
    handle, version, previous = ptr(), U32(), U32()
    target = GUID((U8 * 16).from_buffer_copy(identity.bytes_le))
    event = threading.Event()
    outcome = []
    @callback_type
    def notified(data, context):
        info = data.contents
        if info.source == 8 and bytes(info.guid.data) == identity.bytes_le and info.code in (7, 8):
            outcome.append(info.code)
            event.set()
    def checked(code):
        if code:
            raise OSError(code, 'WLAN scan unavailable; check WLAN service and Windows location permission')
    registered = False
    try:
        checked(api.WlanOpenHandle(2, None, c.byref(version), c.byref(handle)))
        checked(api.WlanRegisterNotification(handle, 8, True, notified, None, None, c.byref(previous)))
        registered = True
        checked(api.WlanScan(handle, c.byref(target), None, None, None))
        finished = event.wait(4)
        status = ('Completed' if outcome and outcome[-1] == 7 else 'Failed') if finished else 'Timed out; cached observations may be stale'
        result = read_wifi()
        result['survey'] = dict(guid=str(identity), status=status, completed=finished and outcome[-1] == 7)
        return result
    finally:
        if registered:
            # Unregister waits for any in-flight callback before Python releases its reference.
            api.WlanRegisterNotification(handle, 0, True, callback_type(), None, None, c.byref(previous))
        if handle.value:
            api.WlanCloseHandle(handle, None)
