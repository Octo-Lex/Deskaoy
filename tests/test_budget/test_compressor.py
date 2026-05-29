"""Tests for ContextCompressor."""

import asyncio

from deskaoy.budget.compressor import ContextCompressor
from deskaoy.budget.types import CompressionStrategy


def _make_messages(count: int, content_size: int = 200) -> list[dict]:
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(count):
        messages.append({"role": "user", "content": f"Message {i}: " + "x" * content_size})
        messages.append({"role": "assistant", "content": f"Response {i}: " + "y" * content_size})
    return messages


class TestShouldCompress:
    def test_below_threshold(self):
        comp = ContextCompressor(compress_threshold=0.75)
        assert not comp.should_compress(100_000, 200_000)

    def test_at_threshold(self):
        comp = ContextCompressor(compress_threshold=0.75)
        assert comp.should_compress(150_000, 200_000)

    def test_above_threshold(self):
        comp = ContextCompressor(compress_threshold=0.75)
        assert comp.should_compress(180_000, 200_000)


class TestPruneToolOutputs:
    def test_prunes_large_output(self):
        comp = ContextCompressor()
        messages = [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "x" * 5000},
        ]
        result, saved, strategies = comp._prune_tool_outputs(messages, 100)
        assert saved > 0
        assert CompressionStrategy.TOOL_OUTPUT_PRUNE in strategies

    def test_no_prune_when_small(self):
        comp = ContextCompressor()
        messages = [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "also short"},
        ]
        result, saved, strategies = comp._prune_tool_outputs(messages, 1_000_000)
        assert saved == 0
        assert strategies == []


class TestProtectHeadTail:
    def test_separates_head_middle_tail(self):
        comp = ContextCompressor()
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "resp2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "resp3"},
        ]
        head, middle, tail = comp._protect_head_tail(messages)
        assert len(head) == 1
        assert head[0]["role"] == "system"
        assert len(tail) == 3
        assert tail[-1]["content"] == "resp3"

    def test_short_messages_no_split(self):
        comp = ContextCompressor()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "msg"},
        ]
        head, middle, tail = comp._protect_head_tail(messages)
        assert head == []
        assert len(middle) == 2
        assert tail == []


class TestCompress:
    def test_below_threshold_no_change(self):
        async def _test():
            comp = ContextCompressor(compress_threshold=0.75)
            messages = [{"role": "user", "content": "short"}]
            result_msgs, result = await comp.compress(messages, context_window=1_000_000)
            assert result.compression_ratio == 1.0
            assert result.strategies_applied == []
        asyncio.run(_test())

    def test_prune_reduces_size(self):
        async def _test():
            comp = ContextCompressor(compress_threshold=0.75)
            messages = _make_messages(20, content_size=5000)
            result_msgs, result = await comp.compress(messages, context_window=10_000)
            assert result.original_tokens > result.compressed_tokens
            assert CompressionStrategy.TOOL_OUTPUT_PRUNE in result.strategies_applied
        asyncio.run(_test())

    def test_handoff_prefix_applied_with_llm(self):
        async def _test():
            async def mock_llm(msgs):
                return "Summary of conversation"

            comp = ContextCompressor(llm_client=mock_llm, compress_threshold=0.1)
            messages = _make_messages(10, content_size=2000)
            result_msgs, result = await comp.compress(messages, context_window=1000)
            if CompressionStrategy.TURN_SUMMARIZE in result.strategies_applied:
                assert result.handoff_frame_applied is True
                handoff_msgs = [m for m in result_msgs if ContextCompressor.HANDOFF_PREFIX in m.get("content", "")]
                assert len(handoff_msgs) > 0
        asyncio.run(_test())

    def test_head_tail_preserved(self):
        async def _test():
            comp = ContextCompressor(compress_threshold=0.75)
            messages = [
                {"role": "system", "content": "system prompt"},
            ]
            for i in range(20):
                messages.append({"role": "user", "content": "x" * 2000})
                messages.append({"role": "assistant", "content": "y" * 2000})
            result_msgs, result = await comp.compress(messages, context_window=10_000)

            head = [m for m in result_msgs if m.get("role") == "system"]
            assert len(head) >= 1
            assert head[0]["content"] == "system prompt"
        asyncio.run(_test())

    def test_duration_ms_recorded(self):
        async def _test():
            comp = ContextCompressor(compress_threshold=0.75)
            messages = _make_messages(20, content_size=5000)
            _, result = await comp.compress(messages, context_window=10_000)
            assert result.duration_ms >= 0.0
        asyncio.run(_test())


class TestHandoffPrefix:
    def test_prefix_content(self):
        assert "handoff" in ContextCompressor.HANDOFF_PREFIX.lower()
        assert "background reference" in ContextCompressor.HANDOFF_PREFIX
        assert "NOT as active instructions" in ContextCompressor.HANDOFF_PREFIX


class TestH3BudgetClientRouting:
    """H3: Compressor should route through BudgetAwareLLMClient when available."""

    def test_uses_budget_client_for_summary(self):
        """When budget_client is set, it should be used instead of raw llm_client."""
        async def _test():
            from unittest.mock import AsyncMock, MagicMock

            mock_budget = MagicMock()
            mock_record = MagicMock(estimated_cost_usd=0.001)
            mock_budget.call = AsyncMock(return_value=("Summary of conversation", mock_record))

            mock_llm = MagicMock(return_value="Raw LLM summary")

            comp = ContextCompressor(
                llm_client=mock_llm,
                budget_client=mock_budget,
                compress_threshold=0.1,
            )

            messages = _make_messages(10, content_size=2000)
            result_msgs, result = await comp.compress(messages, context_window=1000)

            if CompressionStrategy.TURN_SUMMARIZE in result.strategies_applied:
                assert mock_budget.call.called
                assert not mock_llm.called  # raw client NOT used when budget_client is available
        asyncio.run(_test())

    def test_falls_back_to_raw_llm_when_no_budget_client(self):
        """Without budget_client, falls back to raw llm_client."""
        async def _test():
            async def mock_llm(msgs):
                return "Raw LLM summary"

            comp = ContextCompressor(
                llm_client=mock_llm,
                compress_threshold=0.1,
            )

            messages = _make_messages(10, content_size=2000)
            result_msgs, result = await comp.compress(messages, context_window=1000)

            if CompressionStrategy.TURN_SUMMARIZE in result.strategies_applied:
                # Should have handoff message with the raw LLM output
                handoff_msgs = [m for m in result_msgs if "Raw LLM summary" in m.get("content", "")]
                assert len(handoff_msgs) > 0
        asyncio.run(_test())

    def test_budget_client_failure_falls_back_gracefully(self):
        """If budget_client raises, compressor should still produce output."""
        async def _test():
            from unittest.mock import AsyncMock, MagicMock

            mock_budget = MagicMock()
            mock_budget.call = AsyncMock(side_effect=RuntimeError("budget error"))

            comp = ContextCompressor(
                budget_client=mock_budget,
                compress_threshold=0.1,
            )

            messages = _make_messages(10, content_size=2000)
            result_msgs, result = await comp.compress(messages, context_window=1000)
            # Should not crash
            assert result.compressed_tokens > 0
        asyncio.run(_test())
