"""Strict, bounded validation for untrusted v1 snapshots; no I/O."""
from datetime import datetime, timedelta
import json
import math

from ..diagnostics import DiagnosticConfig

MAX_ROUNDS = 256
MAX_BYTES = 512 * 1024
MAX_NODES = 16384
CONFIG_KEYS = {'window_seconds', 'min_samples', 'external_targets',
               'alignment_seconds', 'spike_floor_ms', 'min_spikes'}


def json_bounds(value):
    """Bound traversal before serialization (including cyclic/deep structures)."""
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        if depth > 8 or count > MAX_NODES:
            raise ValueError('Snapshot exceeds depth or node limit')
        kind = type(item)
        if kind is str:
            if len(item) > 1024:
                raise ValueError('Strings must contain at most 1024 characters')
        elif kind in (int, float):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError('Numbers must be finite and JSON representable')
        elif kind is dict:
            if len(item) > MAX_NODES:
                raise ValueError('Object exceeds node limit')
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError('Object keys must be strings')
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif kind is list:
            if len(item) > MAX_NODES:
                raise ValueError('Array exceeds node limit')
            for child in item:
                visit(child, depth + 1)
        elif item is not None and kind is not bool:
            raise ValueError('Snapshot must contain only plain JSON values')

    visit(value, 0)
    size = 0
    try:
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False,
                                      separators=(',', ':')).iterencode(value):
            size += len(chunk.encode('utf-8'))
            if size > MAX_BYTES:
                raise ValueError('Snapshot exceeds 512 KiB')
    except (UnicodeError, OverflowError) as exc:
        raise ValueError('Snapshot must be valid UTF-8 JSON') from exc


def keys(value, required, optional=()):
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - set(optional):
        raise ValueError('Object has missing or unknown keys')


def number(value, minimum=0, maximum=None, *, integer=False):
    if type(value) not in ((int,) if integer else (int, float)):
        raise ValueError('Expected a number, not a boolean or null')
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError('Number outside permitted range')


def utc(value):
    if type(value) is not str or not (value.endswith('Z') or value.endswith('+00:00')) or 'T' not in value:
        raise ValueError('Expected a UTC ISO 8601 timestamp')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Invalid UTC timestamp') from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError('Timestamp must be UTC')
    return parsed


def validate(snapshot):
    """Return a validated config and fresh rounds without changing caller data."""
    json_bounds(snapshot)
    keys(snapshot, {'schema_version', 'captured_at', 'as_of', 'stable_path', 'config', 'rounds'})
    if type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1:
        raise ValueError('Unsupported snapshot schema_version')
    if type(snapshot['stable_path']) is not bool:
        raise ValueError('stable_path must be boolean')
    captured, as_of = utc(snapshot['captured_at']), utc(snapshot['as_of'])
    if as_of < captured:
        raise ValueError('Evaluation precedes snapshot capture')
    cfg = snapshot['config']
    keys(cfg, CONFIG_KEYS)
    number(cfg['window_seconds'], 10, 3600, integer=True)
    number(cfg['min_samples'], 3, 1000, integer=True)
    number(cfg['min_spikes'], 1, 1000, integer=True)
    number(cfg['alignment_seconds'], 0, 1)
    number(cfg['spike_floor_ms'], 0)
    if not cfg['alignment_seconds'] or not cfg['spike_floor_ms']:
        raise ValueError('Alignment and spike thresholds must be positive')
    if type(cfg['external_targets']) is not list or not all(type(t) is str for t in cfg['external_targets']):
        raise ValueError('external_targets must be an IPv4 string list')
    config = DiagnosticConfig(**cfg)
    rows = snapshot['rounds']
    if type(rows) is not list or len(rows) > MAX_ROUNDS:
        raise ValueError('Expected at most 256 rounds')
    targets = {'gateway', *config.external_targets}
    previous_at, previous_utc, anchor_at, anchor_utc = None, None, None, None
    fresh = []
    for row in rows:
        keys(row, {'captured_at', 'at', 'probes'}, {'signal_percent', 'signal_at'})
        stamp = utc(row['captured_at'])
        number(row['at'])
        if stamp > captured or (previous_utc is not None and stamp < previous_utc):
            raise ValueError('Rounds must have chronological UTC capture times')
        if previous_at is not None and row['at'] <= previous_at:
            raise ValueError('Round monotonic times must strictly increase')
        if anchor_at is None:
            anchor_at, anchor_utc = row['at'], stamp
        if abs((stamp - anchor_utc).total_seconds() - (row['at'] - anchor_at)) > 2:
            raise ValueError('UTC and monotonic elapsed times disagree')
        previous_at, previous_utc = row['at'], stamp
        probes = row['probes']
        if type(probes) is not dict or probes.keys() - targets:
            raise ValueError('Unknown probe target')
        for probe in probes.values():
            keys(probe, {'start', 'end', 'ms', 'error'})
            number(probe['start'], row['at'])
            number(probe['end'], probe['start'])
            if probe['ms'] is not None:
                number(probe['ms'], 0, 60000)
            error = probe['error']
            if error is not None and (type(error) is not str or not error.strip() or probe['ms'] is not None):
                raise ValueError('Provider errors require a message and null RTT')
        signal, signal_at = row.get('signal_percent'), row.get('signal_at')
        if signal is not None:
            number(signal, 0, 100)
            if signal_at is None:
                raise ValueError('Signal quality requires its observation time')
        if signal_at is not None:
            number(signal_at)
        if (as_of - stamp).total_seconds() <= config.window_seconds:
            fresh.append(row)
    return config, fresh
