"""Hook shape reuse preserves fresh values, events, errors, and redecoration."""
import gc
import importlib.util
import inspect
import os
import weakref
from pathlib import Path

import pytest


@pytest.fixture
def hooks(monkeypatch):
    path = os.environ.get('USR_HOOK_SIGNATURE_TEST_SOURCE')
    if path:
        spec = importlib.util.spec_from_file_location('hook_signature_candidate_tests', Path(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        from ultima_scraper_api.managers.redis import hooks as module
    events = []

    async def publish(metadata):
        events.append(metadata)

    async def watched():
        return True

    monkeypatch.setattr(module, '_publish_hook_event', publish)
    # These cases cover published hooks: a browser is watching.
    monkeypatch.setattr(module, '_hooks_watched', watched, raising=False)
    return module, events


async def test_events_and_invocation_values_are_fresh(hooks):
    module, events = hooks

    class Service:
        @module.with_hooks
        async def lookup(self, identifier, *, flags):
            return [identifier, flags['page']]

    service = Service()
    assert await service.lookup('first', flags={'page': 1}) == ['first', 1]
    assert await service.lookup('second', flags={'page': 2}) == ['second', 2]
    assert [event['event_type'] for event in events] == ['started', 'finished', 'started', 'finished']
    assert [event['arguments'] for event in events] == [
        {'identifier': 'first', 'flags': {'page': 1}}, {'identifier': 'first', 'flags': {'page': 1}},
        {'identifier': 'second', 'flags': {'page': 2}}, {'identifier': 'second', 'flags': {'page': 2}},
    ]
    assert all(event['function'] == 'lookup' and event['module'] == __name__ for event in events)
    assert all('timestamp' in event for event in events)
    assert all(event['result_type'] == 'list' and event['result_count'] == 2 for event in events[1::2])


async def test_signature_is_inspected_once_for_unchanged_async_shape(hooks, monkeypatch):
    module, events = hooks
    real = inspect.signature
    calls = []

    def observed(func):
        calls.append(func)
        return real(func)

    monkeypatch.setattr(module.inspect, 'signature', observed)

    @module.with_hooks
    async def lookup(identifier):
        return None

    await lookup('first')
    await lookup('second')
    assert len(calls) == 1
    assert len(events) == 4 and all('result_type' not in event for event in events)


async def test_exception_identity_and_error_event_are_preserved(hooks):
    module, events = hooks
    error = ValueError('lookup failed')

    @module.with_hooks
    async def lookup(identifier):
        raise error

    with pytest.raises(ValueError) as caught:
        await lookup('first')
    assert caught.value is error
    assert [event['event_type'] for event in events] == ['started', 'error']
    assert events[-1]['error_type'] == 'ValueError' and events[-1]['error_message'] == 'lookup failed'


async def test_explicit_signature_replacement_refreshes_parameter_names(hooks):
    module, events = hooks

    async def lookup(identifier):
        return identifier

    wrapped = module.with_hooks(lookup)
    await wrapped('first')
    lookup.__signature__ = inspect.Signature([inspect.Parameter('renamed', inspect.Parameter.POSITIONAL_OR_KEYWORD)])
    await wrapped('second')
    assert events[0]['arguments'] == {'identifier': 'first'}
    assert events[2]['arguments'] == {'renamed': 'second'}


async def test_wrapped_signature_replacement_is_observed(hooks):
    module, events = hooks

    async def lookup(identifier):
        return identifier

    async def outer(*args, **kwargs):
        return await lookup(*args, **kwargs)

    outer.__wrapped__ = lookup
    wrapped = module.with_hooks(outer)
    await wrapped('first')
    lookup.__signature__ = inspect.Signature([inspect.Parameter('wrapped_name', inspect.Parameter.POSITIONAL_OR_KEYWORD)])
    await wrapped('second')
    assert events[2]['arguments'] == {'wrapped_name': 'second'}


async def test_code_replacement_is_observed(hooks):
    module, events = hooks

    async def lookup(identifier):
        return identifier

    async def replacement(new_name):
        return new_name

    wrapped = module.with_hooks(lookup)
    await wrapped('first')
    lookup.__code__ = replacement.__code__
    await wrapped('second')
    assert events[2]['arguments'] == {'new_name': 'second'}


async def test_invocation_objects_are_not_retained_by_shape_cache(hooks):
    module, events = hooks

    class Payload:
        pass

    @module.with_hooks
    async def lookup(payload):
        return None

    payload = Payload()
    reference = weakref.ref(payload)
    await lookup(payload)
    del payload
    gc.collect()
    assert reference() is None
    assert events[0]['arguments'] == {'payload': '<Payload>'}


async def test_invalid_replaced_signature_retains_original_failure(hooks):
    module, events = hooks

    async def lookup(identifier):
        return identifier

    wrapped = module.with_hooks(lookup)
    await wrapped('first')
    lookup.__signature__ = 'invalid'
    with pytest.raises(TypeError):
        await wrapped('second')
    assert len(events) == 2


def test_sync_functions_keep_existing_no_publication_behavior(hooks):
    module, events = hooks

    @module.with_hooks
    def lookup(identifier):
        return identifier

    assert lookup('value') == 'value'
    assert events == []


def test_direct_metadata_calls_keep_fresh_signature_behavior(hooks):
    module, _ = hooks

    def lookup(identifier):
        return identifier

    assert module._get_hook_metadata(lookup, ('first',), {}, 'started')['arguments'] == {'identifier': 'first'}
    lookup.__signature__ = inspect.Signature([inspect.Parameter('direct_name', inspect.Parameter.POSITIONAL_OR_KEYWORD)])
    assert module._get_hook_metadata(lookup, ('second',), {}, 'started')['arguments'] == {'direct_name': 'second'}
