"""Regression checks for the local Ollama chat agent (issue #18)."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import patch
from urllib.error import URLError

from fastapi import HTTPException

from app import local_agent
from app.local_agent import (
    OllamaRequestError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    chat_with_local_agent,
)
from app.main import LocalChatRequest, chat_models, local_chat

MODEL = "qwen3.5:4b"
FAKE_VEHICLES = {
    "NS-0001": {"serial": "NS-0001", "make": "Demo", "model": "One", "year": 2020},
    "NS-0002": {"serial": "NS-0002", "make": "Demo", "model": "Two", "year": 2021},
}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class OllamaRequestErrorMappingTests(unittest.TestCase):
    def test_read_timeout_is_reported_as_timeout_not_unreachable(self) -> None:
        with patch.object(local_agent, "urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(OllamaTimeoutError) as caught:
                local_agent._ollama_request("/api/chat", {"model": MODEL})
        self.assertIn(f"{local_agent.OLLAMA_TIMEOUT_SECONDS} seconds", str(caught.exception))
        self.assertIn("OLLAMA_TIMEOUT_SECONDS", str(caught.exception))

    def test_connect_timeout_is_reported_as_timeout(self) -> None:
        with patch.object(local_agent, "urlopen", side_effect=URLError(TimeoutError("timed out"))):
            with self.assertRaises(OllamaTimeoutError):
                local_agent._ollama_request("/api/tags")

    def test_connection_refused_is_reported_as_unavailable(self) -> None:
        with patch.object(local_agent, "urlopen", side_effect=URLError(ConnectionRefusedError())):
            with self.assertRaises(OllamaUnavailableError) as caught:
                local_agent._ollama_request("/api/tags")
        self.assertNotIsInstance(caught.exception, OllamaTimeoutError)
        self.assertIn("127.0.0.1:11434", str(caught.exception))


class LocalAgentLoopTests(unittest.TestCase):
    def test_ollama_error_inside_mcp_client_is_not_wrapped_in_exception_group(self) -> None:
        for error in (
            OllamaTimeoutError("slow"),
            OllamaUnavailableError("down"),
            OllamaRequestError("bad"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(local_agent, "list_local_models", return_value=[MODEL]),
                    patch.object(local_agent, "_ollama_request", side_effect=error),
                ):
                    with self.assertRaises(type(error)) as caught:
                        run(chat_with_local_agent(MODEL, "How many vehicles?", []))
                self.assertIs(type(caught.exception), type(error))

    def test_non_ollama_exception_group_is_not_swallowed(self) -> None:
        group = ExceptionGroup("other", [ValueError("not ollama")])
        self.assertIsNone(local_agent._find_ollama_error(group))
        nested = ExceptionGroup("outer", [ExceptionGroup("inner", [OllamaTimeoutError("slow")])])
        self.assertIsInstance(local_agent._find_ollama_error(nested), OllamaTimeoutError)

    def test_chat_disables_thinking_and_grounds_reply_in_mcp_tool_result(self) -> None:
        payloads: list[dict[str, Any]] = []
        replies = [
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "dataset_summary", "arguments": {}}}
            ]}},
            {"message": {"role": "assistant", "content": "There are 2 synthetic records."}},
        ]

        def fake_ollama(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            self.assertEqual(path, "/api/chat")
            payloads.append(json.loads(json.dumps(payload)))
            return replies[len(payloads) - 1]

        with (
            patch.object(local_agent, "list_local_models", return_value=[MODEL]),
            patch.object(local_agent, "_ollama_request", side_effect=fake_ollama),
            patch("app.mcp_server.load_vehicles", return_value=FAKE_VEHICLES),
        ):
            result = run(chat_with_local_agent(MODEL, "How many vehicles?", []))

        self.assertEqual(len(payloads), 2)
        for payload in payloads:
            self.assertIs(payload["think"], False)
            self.assertFalse(payload["stream"])
        tool_names = {tool["function"]["name"] for tool in payloads[0]["tools"]}
        self.assertIn("dataset_summary", tool_names)
        tool_messages = [m for m in payloads[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 1)
        tool_result = json.loads(tool_messages[0]["content"])
        self.assertEqual(tool_result["record_count"], 2)
        self.assertTrue(tool_result["synthetic_data"])
        self.assertEqual(result["tools_used"], ["dataset_summary"])
        self.assertEqual(result["reply"], "There are 2 synthetic records.")
        self.assertIs(result["out_of_scope"], False)


class TopicGuardrailTests(unittest.TestCase):
    """Issue #24: the chat answers dealership service questions only."""

    def chat_with_replies(self, *replies: dict[str, Any], message: str = "question") -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payloads: list[dict[str, Any]] = []

        def fake_ollama(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            payloads.append(json.loads(json.dumps(payload)))
            return replies[len(payloads) - 1]

        with (
            patch.object(local_agent, "list_local_models", return_value=[MODEL]),
            patch.object(local_agent, "_ollama_request", side_effect=fake_ollama),
            patch("app.mcp_server.load_vehicles", return_value=FAKE_VEHICLES),
        ):
            result = run(chat_with_local_agent(MODEL, message, []))
        return result, payloads

    def test_system_prompt_states_scope_and_out_of_scope_marker(self) -> None:
        _, payloads = self.chat_with_replies({"message": {"role": "assistant", "content": "OUT_OF_SCOPE"}})
        system = payloads[0]["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("dealership service-lane topics", system["content"])
        self.assertIn("general knowledge", system["content"])
        self.assertIn(local_agent.OUT_OF_SCOPE_MARKER, system["content"])

    def test_out_of_scope_marker_returns_fixed_refusal(self) -> None:
        result, _ = self.chat_with_replies(
            {"message": {"role": "assistant", "content": "OUT_OF_SCOPE"}}, message="What is the capital of France?"
        )
        self.assertEqual(result["reply"], local_agent.OUT_OF_SCOPE_REPLY)
        self.assertIs(result["out_of_scope"], True)
        self.assertEqual(result["tools_used"], [])

    def test_model_off_topic_text_is_never_shown(self) -> None:
        result, _ = self.chat_with_replies(
            {"message": {"role": "assistant", "content": "Paris is the capital of France."}},
            message="What is the capital of France?",
        )
        self.assertNotIn("Paris", result["reply"])
        self.assertTrue(result["reply"].startswith(local_agent.OUT_OF_SCOPE_REPLY))
        self.assertEqual(result["tools_used"], [])

    def test_marker_after_tool_use_still_refuses(self) -> None:
        result, _ = self.chat_with_replies(
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "dataset_summary", "arguments": {}}}
            ]}},
            {"message": {"role": "assistant", "content": "out_of_scope"}},
        )
        self.assertEqual(result["reply"], local_agent.OUT_OF_SCOPE_REPLY)
        self.assertIs(result["out_of_scope"], True)

    def test_uninstalled_model_is_rejected_before_any_chat_request(self) -> None:
        with (
            patch.object(local_agent, "list_local_models", return_value=["other:1b"]),
            patch.object(local_agent, "_ollama_request") as ollama,
        ):
            with self.assertRaises(OllamaRequestError):
                run(chat_with_local_agent(MODEL, "hi", []))
        ollama.assert_not_called()


class ChatApiErrorTests(unittest.TestCase):
    def request(self) -> LocalChatRequest:
        return LocalChatRequest(model=MODEL, message="How many vehicles?", history=[])

    def test_model_timeout_returns_504_with_timeout_message(self) -> None:
        error = OllamaTimeoutError("The local model did not respond within 600 seconds.")
        with patch("app.main.chat_with_local_agent", side_effect=error):
            with self.assertRaises(HTTPException) as caught:
                run(local_chat(self.request()))
        self.assertEqual(caught.exception.status_code, 504)
        self.assertIn("600 seconds", caught.exception.detail)

    def test_unreachable_ollama_returns_503(self) -> None:
        with patch("app.main.chat_with_local_agent", side_effect=OllamaUnavailableError("down")):
            with self.assertRaises(HTTPException) as caught:
                run(local_chat(self.request()))
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("Start the local Ollama app", caught.exception.detail)

    def test_model_list_timeout_returns_504(self) -> None:
        with patch("app.main.list_local_models", side_effect=OllamaTimeoutError("slow")):
            with self.assertRaises(HTTPException) as caught:
                run(chat_models())
        self.assertEqual(caught.exception.status_code, 504)


if __name__ == "__main__":
    unittest.main()
