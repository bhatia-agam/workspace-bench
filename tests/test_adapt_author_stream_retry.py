"""``author._transport_error``: a dropped authoring stream is retried (``STREAM_RETRIES``)."""

from wsbench.adapt import author


def test_transport_errors_are_recognised():
    class RemoteProtocolError(Exception):  # the httpx class name the SDK surfaces unwrapped
        pass

    assert author._transport_error(RemoteProtocolError("peer closed connection"))
    assert not author._transport_error(ValueError("bad json"))
    assert author.STREAM_RETRIES >= 1
