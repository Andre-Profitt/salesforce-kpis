"""
Tests for flywheel log contract compliance.

Verifies:
- Flywheel records conform to OpenAI format
- Emitter creates valid JSONL files
- Loaders can read and query logs
- Schema validation works correctly
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

from app.flywheel.schema import FlywheelRecord, Request, Response, Message
from app.flywheel.emitter import FlywheelEmitter
from app.flywheel.loaders.to_jsonl import FlywheelJSONLLoader


class TestFlywheelContract:
    """Test suite for flywheel log contract."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create temporary log directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def emitter(self, temp_log_dir):
        """Create flywheel emitter."""
        return FlywheelEmitter(log_dir=temp_log_dir)

    @pytest.fixture
    def loader(self, temp_log_dir):
        """Create JSONL loader."""
        return FlywheelJSONLLoader(log_dir=temp_log_dir)

    @pytest.fixture
    def sample_request(self):
        """Create sample request."""
        return Request(
            model="test-model",
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="User message")
            ]
        )

    @pytest.fixture
    def sample_response(self):
        """Create sample response."""
        return Response(
            id="test-123",
            created=int(datetime.utcnow().timestamp()),
            model="test-model",
            choices=[{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': 'Response content'
                },
                'finish_reason': 'stop'
            }]
        )

    def test_flywheel_record_validation(self, sample_request, sample_response):
        """Test flywheel record Pydantic validation."""
        record = FlywheelRecord(
            timestamp=int(datetime.utcnow().timestamp()),
            client_id="test-client",
            workload_id="test.workload",
            request=sample_request,
            response=sample_response
        )

        assert record.timestamp > 0
        assert record.client_id == "test-client"
        assert record.workload_id == "test.workload"
        assert record.request.model == "test-model"
        assert len(record.request.messages) == 2

    def test_openai_format_compliance(self, sample_request, sample_response):
        """Test OpenAI format compliance."""
        record = FlywheelRecord(
            timestamp=int(datetime.utcnow().timestamp()),
            client_id="test-client",
            workload_id="test.workload",
            request=sample_request,
            response=sample_response
        )

        # Serialize to dict
        record_dict = record.model_dump()

        # Check OpenAI-compatible structure
        assert 'request' in record_dict
        assert 'response' in record_dict
        assert 'messages' in record_dict['request']
        assert 'choices' in record_dict['response']

        # Check message format
        for msg in record_dict['request']['messages']:
            assert 'role' in msg
            assert 'content' in msg

        # Check response format
        choice = record_dict['response']['choices'][0]
        assert 'message' in choice
        assert 'finish_reason' in choice

    def test_emitter_creates_file(self, emitter, sample_request, sample_response):
        """Test emitter creates JSONL file."""
        record = FlywheelRecord(
            timestamp=int(datetime.utcnow().timestamp()),
            client_id="test-client",
            workload_id="test.workload",
            request=sample_request,
            response=sample_response
        )

        emitter.emit(record)

        # Check file was created
        log_file = Path(emitter.log_dir) / "test_workload.jsonl"
        assert log_file.exists()

    def test_emitter_appends_records(self, emitter, sample_request, sample_response):
        """Test emitter appends multiple records."""
        for i in range(3):
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id=f"client-{i}",
                workload_id="test.workload",
                request=sample_request,
                response=sample_response
            )
            emitter.emit(record)

        # Read file
        log_file = Path(emitter.log_dir) / "test_workload.jsonl"
        with open(log_file) as f:
            lines = f.readlines()

        assert len(lines) == 3

        # Verify each line is valid JSON
        for line in lines:
            record_dict = json.loads(line)
            assert 'client_id' in record_dict

    def test_loader_lists_workloads(self, emitter, loader, sample_request, sample_response):
        """Test loader lists workloads."""
        # Emit records for different workloads
        for workload in ['workload.one', 'workload.two']:
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id="test-client",
                workload_id=workload,
                request=sample_request,
                response=sample_response
            )
            emitter.emit(record)

        workloads = loader.list_workloads()
        assert 'workload.one' in workloads
        assert 'workload.two' in workloads

    def test_loader_iterates_records(self, emitter, loader, sample_request, sample_response):
        """Test loader iterates records."""
        # Emit 5 records
        for i in range(5):
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id=f"client-{i}",
                workload_id="test.workload",
                request=sample_request,
                response=sample_response
            )
            emitter.emit(record)

        # Iterate and count
        count = 0
        for record in loader.iter_records('test.workload'):
            count += 1
            assert 'client_id' in record

        assert count == 5

    def test_loader_loads_records(self, emitter, loader, sample_request, sample_response):
        """Test loader loads records into memory."""
        # Emit 3 records
        for i in range(3):
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id=f"client-{i}",
                workload_id="test.workload",
                request=sample_request,
                response=sample_response
            )
            emitter.emit(record)

        records = loader.load_records('test.workload')

        assert len(records) == 3
        assert records[0]['client_id'] == 'client-0'
        assert records[2]['client_id'] == 'client-2'

    def test_loader_limit(self, emitter, loader, sample_request, sample_response):
        """Test loader respects limit."""
        # Emit 10 records
        for i in range(10):
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id=f"client-{i}",
                workload_id="test.workload",
                request=sample_request,
                response=sample_response
            )
            emitter.emit(record)

        # Load with limit
        records = loader.load_records('test.workload', limit=5)

        assert len(records) == 5
        # Should be last 5 records
        assert records[-1]['client_id'] == 'client-9'

    def test_outcome_distribution(self, emitter, loader, sample_request, sample_response):
        """Test outcome distribution calculation."""
        # Emit records with different outcomes
        outcomes = ['success', 'success', 'error', 'skipped']

        for outcome in outcomes:
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id="test-client",
                workload_id="test.workload",
                request=sample_request,
                response=sample_response,
                metadata={'outcome': outcome}
            )
            emitter.emit(record)

        distribution = loader.get_outcome_distribution('test.workload')

        assert distribution['success'] == 2
        assert distribution['error'] == 1
        assert distribution['skipped'] == 1

    def test_routing_decision_emission(self, emitter):
        """Test routing decision emission."""
        lead_data = {
            'Company': 'Acme Corp',
            'NumberOfEmployees': 500,
            'Country': 'US'
        }

        decision = {
            'segment': 'MM',
            'region': 'NA',
            'owner_id': '005xx000001',
            'outcome': 'success'
        }

        emitter.emit_routing_decision(
            lead_id='00Qxx000001',
            lead_data=lead_data,
            decision=decision,
            policy_version='v1.0.0',
            latency_ms=45.2
        )

        # Verify file was created
        log_file = Path(emitter.log_dir) / "lead_route.jsonl"
        assert log_file.exists()

        # Read and verify structure
        with open(log_file) as f:
            record_dict = json.loads(f.readline())

        assert record_dict['workload_id'] == 'lead.route'
        assert record_dict['lead_id'] == '00Qxx000001'
        assert record_dict['policy_version'] == 'v1.0.0'
        assert record_dict['metadata']['latency_ms'] == 45.2

    def test_first_touch_emission(self, emitter):
        """Test first touch detection emission."""
        candidate = {
            'source': 'Task',
            'user_id': '005xx000001',
            'timestamp': '2025-01-15T10:30:00Z',
            'existing_timestamp': None
        }

        result = {
            'status': 'updated',
            'reason': 'new_earliest',
            'ttfr_minutes': 45
        }

        emitter.emit_first_touch_detection(
            lead_id='00Qxx000001',
            candidate_response=candidate,
            detection_result=result,
            latency_ms=12.3
        )

        # Verify file was created
        log_file = Path(emitter.log_dir) / "first_touch_detect.jsonl"
        assert log_file.exists()

    def test_export_for_training(self, emitter, loader, sample_request, sample_response):
        """Test export for LLM training."""
        # Emit records with different outcomes
        for i, outcome in enumerate(['success', 'success', 'error']):
            record = FlywheelRecord(
                timestamp=int(datetime.utcnow().timestamp()),
                client_id=f"client-{i}",
                workload_id="test.workload",
                request=sample_request,
                response=sample_response,
                metadata={'outcome': outcome}
            )
            emitter.emit(record)

        # Export only successful records
        output_file = Path(emitter.log_dir) / "training.jsonl"

        count = loader.export_for_training(
            'test.workload',
            str(output_file),
            outcome_filter=['success']
        )

        assert count == 2

        # Verify training format
        with open(output_file) as f:
            training_record = json.loads(f.readline())

        assert 'messages' in training_record
        assert len(training_record['messages']) == 3  # system + user + assistant
