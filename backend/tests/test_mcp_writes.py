"""Checks for MCP write tools and advisor-confirmed chat proposals (issue #44)."""

from __future__ import annotations

import isolation  # noqa: F401  (must run before app imports)

import asyncio
import copy
import json
import unittest
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from mcp import Client

from app import local_agent
from app.main import apply_chat_proposal, discard_chat_proposal
from app.mcp_server import mcp_server
from test_obd_telemetry import FakeSupabase

MODEL = "qwen3.5:4b"
SERIAL = "NS-0001"
RECORD: dict[str, Any] = {
    "serial": SERIAL, "make": "Demo", "model": "Sedan", "year": 2021,
    "mileage": 48120, "mileageDate": "Recorded today", "completeness": "Complete demo record",
    "history": [{"date": "Apr 18, 2026", "name": "Engine oil and filter", "detail": "Routine service", "mileage": "39,820 mi"}],
    "recs": [{"name": "Engine oil and filter", "status": "Due", "kind": "due", "text": "t", "evidence": "e", "rule": "r", "safety": False}],
    "incomplete": False, "conflicting": False,
}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    async with Client(mcp_server) as client:
        result = await client.call_tool(name, args)
        return result.structured_content


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeSupabase([{"serial": SERIAL, "record": copy.deepcopy(RECORD)}])
        self.patches = [patch(f"app.{module}.get_supabase_client", return_value=self.client) for module in ("data_store", "record_edits")]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def stored(self, serial: str = SERIAL) -> dict[str, Any]:
        return self.client.rows[serial]["record"]


class McpWriteToolTests(StoreTestCase):
    def test_write_tools_are_registered_and_read_tools_unchanged(self) -> None:
        async def names() -> set[str]:
            async with Client(mcp_server) as client:
                return {tool.name for tool in (await client.list_tools()).tools}

        tools = run(names())
        for name in ("search_vehicle_records", "get_vehicle_record", "create_customer_draft", "create_record_request_draft",
                     "dataset_summary", "add_vehicle", "update_vehicle_details", "update_vehicle_mileage",
                     "record_completed_service", "edit_history_entry", "add_recommendation",
                     "update_recommendation", "remove_recommendation"):
            self.assertIn(name, tools)
        self.assertNotIn("delete_history_entry", tools)

    def test_add_vehicle_and_recommendation_write_and_log_mcp_agent(self) -> None:
        added = run(call_tool("add_vehicle", {"serial": "mcp-car-1", "make": "Ironvale", "model": "Forge", "year": 2024}))
        self.assertTrue(added["saved"])
        self.assertEqual(added["serial"], "MCP-CAR-1")
        self.assertEqual(self.stored("MCP-CAR-1")["changeLog"][-1]["actor"], "MCP agent")
        rec = run(call_tool("add_recommendation", {"serial": SERIAL, "name": "Cabin air filter", "status": "Coming up",
                                                    "text": "Dusty filter seen.", "evidence": "Visual check."}))
        self.assertTrue(rec["saved"])
        self.assertIn("Cabin air filter", rec["vehicle"]["open_recommendations"])
        self.assertEqual(self.stored()["recs"][-1]["source"], "advisor_entered")

    def test_invalid_stale_or_unknown_writes_return_saved_false_without_writing(self) -> None:
        before = copy.deepcopy(self.client.rows)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        cases = [
            ("update_vehicle_mileage", {"serial": SERIAL, "mileage": 50000, "mileage_date": tomorrow}),
            ("update_vehicle_mileage", {"serial": SERIAL, "mileage": -5, "mileage_date": "2026-01-01"}),
            ("add_vehicle", {"serial": "ns-0001", "make": "A", "model": "B", "year": 2020}),
            ("add_vehicle", {"serial": "OK-9", "make": "A", "model": "B", "year": 2020, "mileage": 10}),
            ("edit_history_entry", {"serial": SERIAL, "index": 0, "expected_date": "Apr 18, 2026", "expected_name": "Wrong",
                                    "service_date": "2026-04-18", "name": "X"}),
            ("remove_recommendation", {"serial": SERIAL, "index": 0, "expected_name": "Wrong"}),
            ("record_completed_service", {"serial": "NOPE-1", "service_name": "Oil", "service_date": "2026-01-01"}),
        ]
        for tool, args in cases:
            with self.subTest(tool=tool, args=args):
                result = run(call_tool(tool, args))
                self.assertFalse(result["saved"])
                self.assertTrue(result["error"])
        self.assertEqual(self.client.rows, before)


class ChatProposalTests(StoreTestCase):
    def chat_with_write_call(self, tool: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payloads: list[dict[str, Any]] = []
        replies = [
            {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": tool, "arguments": args}}]}},
            {"message": {"role": "assistant", "content": "I proposed the change; please confirm it."}},
        ]

        def fake_ollama(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            payloads.append(json.loads(json.dumps(payload)))
            return replies[len(payloads) - 1]

        with patch.object(local_agent, "list_local_models", return_value=[MODEL]), patch.object(
            local_agent, "_ollama_request", side_effect=fake_ollama
        ):
            result = run(local_agent.chat_with_local_agent(MODEL, "Record an oil change for NS-0001", []))
        return result, payloads

    def test_chat_write_becomes_a_proposal_and_nothing_is_saved(self) -> None:
        before = copy.deepcopy(self.client.rows)
        args = {"serial": SERIAL, "service_name": "Engine oil and filter", "service_date": "2026-05-01", "mileage": 48300,
                "recommendation_name": "Engine oil and filter"}
        result, payloads = self.chat_with_write_call("record_completed_service", args)
        self.assertEqual(self.client.rows, before)
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["tool"], "record_completed_service")
        self.assertIn("Record 'Engine oil and filter' done on NS-0001", proposal["summary"])
        self.assertIn("record_completed_service (proposed)", result["tools_used"])
        tool_message = [m for m in payloads[1]["messages"] if m["role"] == "tool"][0]["content"]
        self.assertIn("NOT SAVED", tool_message)
        self.assertIn("never say a change was saved", payloads[0]["messages"][0]["content"])

    def test_apply_saves_once_with_chat_actor_then_404(self) -> None:
        result, _ = self.chat_with_write_call("add_recommendation", {
            "serial": SERIAL, "name": "Cabin air filter", "status": "Coming up", "text": "Dusty.", "evidence": "Seen today."})
        proposal_id = result["proposals"][0]["id"]
        applied = apply_chat_proposal(proposal_id)
        self.assertTrue(applied["saved"])
        self.assertEqual(self.stored()["changeLog"][-1]["actor"], "advisor via chat (confirmed)")
        with self.assertRaises(HTTPException) as caught:
            apply_chat_proposal(proposal_id)
        self.assertEqual(caught.exception.status_code, 404)

    def test_apply_of_invalid_proposal_returns_422_without_writing(self) -> None:
        before = copy.deepcopy(self.client.rows)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result, _ = self.chat_with_write_call("update_vehicle_mileage", {"serial": SERIAL, "mileage": 50000, "mileage_date": tomorrow})
        with self.assertRaises(HTTPException) as caught:
            apply_chat_proposal(result["proposals"][0]["id"])
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("future", caught.exception.detail)
        self.assertEqual(self.client.rows, before)

    def test_discard_and_expiry_and_unknown_ids(self) -> None:
        result, _ = self.chat_with_write_call("remove_recommendation", {"serial": SERIAL, "index": 0, "expected_name": "Engine oil and filter"})
        proposal_id = result["proposals"][0]["id"]
        self.assertTrue(discard_chat_proposal(proposal_id)["discarded"])
        for call in (lambda: apply_chat_proposal(proposal_id), lambda: discard_chat_proposal("not-a-real-id")):
            with self.assertRaises(HTTPException) as caught:
                call()
            self.assertEqual(caught.exception.status_code, 404)
        expired = local_agent.create_proposal("remove_recommendation", {"serial": SERIAL, "index": 0, "expected_name": "Engine oil and filter"})
        with local_agent._proposals_lock:
            local_agent._proposals[expired["id"]]["created"] -= local_agent.PROPOSAL_TTL_SECONDS + 1
        with self.assertRaises(HTTPException) as caught:
            apply_chat_proposal(expired["id"])
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(len(self.stored()["recs"]), 1)


if __name__ == "__main__":
    unittest.main()
