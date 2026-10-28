import pytest
from pydantic import BaseModel

from askthe.adapters.memory import MemoryLLMClient
from askthe.core.interfaces import LLMClient, LLMTask


class Out(BaseModel):
    value: int


def test_scripted_responses_are_returned_in_order_and_calls_recorded():
    llm = MemoryLLMClient(models={"extract": "some-model"})
    assert isinstance(llm, LLMClient)
    llm.script(LLMTask.EXTRACT, Out(value=1), lambda system, prompt: Out(value=len(prompt)))

    assert llm.generate_structured(LLMTask.EXTRACT, "sys", "p", Out).value == 1
    assert llm.generate_structured(LLMTask.EXTRACT, "sys", "four", Out).value == 4
    assert llm.calls[-1] == (LLMTask.EXTRACT, "sys", "four")
    assert llm.model_for(LLMTask.EXTRACT) == "some-model"
    assert llm.model_for(LLMTask.ANSWER) == "memory"


def test_running_out_or_wrong_type_fails_loudly():
    llm = MemoryLLMClient()
    with pytest.raises(LookupError):
        llm.generate_text(LLMTask.ANSWER, "s", "p")
    llm.script(LLMTask.ANSWER, Out(value=1))
    with pytest.raises(TypeError):
        llm.generate_text(LLMTask.ANSWER, "s", "p")
