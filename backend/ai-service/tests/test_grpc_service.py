import pytest
import grpc
import time
from app.api import communication_pb2
from app.api.grpc_service import CommunicationServiceServicer

class MockContext(grpc.ServicerContext):
    def __init__(self):
        self._invocation_metadata = []
        self._peer = "ipv4:127.0.0.1:12345"
        self._code = grpc.StatusCode.OK
        self._details = ""

    def abort(self, code, details):
        self._code = code
        self._details = details
        raise Exception(f"Aborted: {code} - {details}")

    def abort_with_status(self, status):
        self._code = status.code
        self._details = status.details
        raise Exception(f"Aborted: {status.code} - {status.details}")

    def add_callback(self, callback):
        pass

    def auth_context(self):
        return {}

    def cancel(self):
        pass

    def disable_next_message_compression(self):
        pass

    def invocation_metadata(self):
        return self._invocation_metadata

    def is_active(self):
        return True

    def peer(self):
        return self._peer

    def peer_identities(self):
        return []

    def peer_identity_key(self):
        return None

    def send_initial_metadata(self, initial_metadata):
        pass

    def set_code(self, code):
        self._code = code

    def set_details(self, details):
        self._details = details

    def set_trailing_metadata(self, trailing_metadata):
        pass

    def time_remaining(self):
        return None

def test_ping_success():
    servicer = CommunicationServiceServicer()
    context = MockContext()
    
    trace_id = "test-trace-123"
    timestamp = int(time.time() * 1000)
    
    request = communication_pb2.PingRequest(
        trace_id=trace_id,
        timestamp=timestamp
    )
    
    response = servicer.Ping(request, context)
    
    assert response.trace_id == trace_id
    assert response.source == "python-ai-service"
    assert response.timestamp >= timestamp
