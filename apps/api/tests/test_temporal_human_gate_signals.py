import asyncio
import inspect
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowHandle

from app.canvas_runs import create_canvas_run
from app.canvas_temporal import CanvasRunWorkflow
from app.database import SessionLocal
from app.domain import CanvasRunRequest, NodeStatus
from app.infrastructure.persistence import run_operations
from app import workflow_runtime_service


@pytest.mark.parametrize('source', ['CANVAS_DRAFT', 'WORKFLOW_VERSION'])
@pytest.mark.parametrize('action', ['approve', 'select_artifact'])
def test_human_gate_signal_uses_installed_temporal_sdk_signature(client, monkeypatch, source, action):
    parameters = {'caption_document': {'schema_version': 'caption.document.v1'}}
    node_key = 'subtitle.design' if action == 'approve' else 'candidate.select'
    with SessionLocal() as db:
        run = create_canvas_run(db, CanvasRunRequest(
            canvas_id='signal-test',
            nodes=[{'id': 'gate', 'data': {'key': node_key, 'contractVersion': 1}}],
        ))
        run.source_type = source
        run.status = NodeStatus.WAITING_INPUT
        run.node_runs[0].status = NodeStatus.WAITING_INPUT
        db.commit()
        run_id = run.id

    calls = []

    class Handle:
        async def signal(self, *args, **kwargs):
            # Check the real SDK signature rather than a permissive AsyncMock.
            bound = inspect.signature(WorkflowHandle.signal).bind(self, *args, **kwargs)
            calls.append(bound.arguments)

    class Client:
        def get_workflow_handle_for(self, workflow, workflow_id):
            assert workflow is CanvasRunWorkflow.run
            assert workflow_id == f'frameflow/canvas/{run_id}'
            return Handle()

    async def temporal_client():
        return Client()

    module = run_operations if source == 'CANVAS_DRAFT' else workflow_runtime_service
    monkeypatch.setattr(module, 'uses_temporal', lambda: True)
    monkeypatch.setattr(module, 'temporal_client', temporal_client)
    if source == 'CANVAS_DRAFT':
        operations = run_operations.LegacySqlAlchemyRunOperations()
        command = SimpleNamespace(run_id=run_id, canvas_node_id='gate', parameters=parameters, artifact_id='chosen')
        method = operations.approve_canvas_node if action == 'approve' else operations.select_canvas_candidate
        asyncio.run(method(command))
    else:
        with SessionLocal() as db:
            asyncio.run(workflow_runtime_service.respond_to_workflow_run(
                db, run_id=run_id, node_id='gate', action=action,
                parameters=parameters, artifact_id='chosen',
            ))
    assert len(calls) == 1
    assert calls[0]['signal'] is (CanvasRunWorkflow.node_approved if action == 'approve' else CanvasRunWorkflow.candidate_selected)
    assert calls[0]['args'] == ['gate', parameters if action == 'approve' else 'chosen']


def test_caption_approval_payload_decodes_with_signal_type_hints():
    from typing import get_type_hints
    from temporalio.converter import DataConverter

    parameters = {
        'caption_document': {
            'schema_version': 'caption.document.v1',
            'content': {'type': 'doc', 'content': [
                {'type': 'paragraph', 'content': [{'type': 'text', 'text': '猫 · 고양이'}]},
            ]},
            'default_style': {'font_size': 54, 'bold': True, 'font_id': None},
        },
    }

    async def roundtrip():
        converter = DataConverter.default
        hints = get_type_hints(CanvasRunWorkflow.node_approved)
        payloads = await converter.encode(['gate', parameters])
        return await converter.decode(payloads, [hints['canvas_node_id'], hints['parameters']])

    assert asyncio.run(roundtrip()) == ['gate', parameters]
