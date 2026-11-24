"""Tests for reading LLM answers and for the ranking metric, run with: python -m pytest"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import llm_map  # noqa: E402
import train_distress  # noqa: E402


def test_llm_answer_with_extra_text_is_parsed():
    text = 'Here you go:\n{"results": [{"id": 0, "item_code": "cash", "confidence": 0.9},' \
           ' {"id": 1, "item_code": "made_up_item", "confidence": 0.7}]}\nThanks'
    out = llm_map.parse(text, 2)
    assert out[0] == ("cash", 0.9)
    assert out[1] == ("none", 0.7)   # labels outside the standard list are not trusted


def test_llm_answer_that_skips_a_line_is_rejected():
    with pytest.raises(ValueError):
        llm_map.parse('{"results": [{"id": 0, "item_code": "cash", "confidence": 1}]}', 2)


def test_top_k_stats():
    y = np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 1] * 10)          # 20 positives in 100
    score = np.where(y == 1, 1.0, 0.0)
    score[[9, 19]] = -1.0                                       # two positives ranked last
    s = train_distress.top_k_stats(y, score, frac=0.10)
    assert s["flagged"] == 10 and s["caught"] == 10
    assert s["capture_rate"] == pytest.approx(0.5)
    assert s["lift"] == pytest.approx(5.0)
