import pytest
from pydantic import BaseModel

from askthe.adapters.memory import MemoryLLMClient
from askthe.core.interfaces import LLMClient, LLMTask


class Out(BaseModel):
    value: int


def test_scripted_responses_are_returned_in_order_and_calls_recorded():
    llm = MemoryLLMClient(models={"extract": "some-model"})
    assert isinstance(llm, LLMClient)
    llm.script(LLMTask.EXTRACT, Out(value=1), lambda context, prompt: Out(value=len(prompt)))

    first = llm.generate_structured(LLMTask.EXTRACT, "sys", "p", Out)
    assert first.value.value == 1 and first.model == "some-model"
    assert (
        llm.generate_structured(LLMTask.EXTRACT, "sys", "four", Out, context="c").value.value == 4
    )
    assert llm.calls[-1] == (LLMTask.EXTRACT, "sys", "four", "c")
    assert llm.model_for(LLMTask.ANSWER) == "memory"


def test_running_out_or_wrong_type_fails_loudly():
    class Other(BaseModel):
        x: int

    llm = MemoryLLMClient()
    with pytest.raises(LookupError):
        llm.generate_structured(LLMTask.ANSWER, "s", "p", Out)
    llm.script(LLMTask.ANSWER, Other(x=1))
    with pytest.raises(TypeError):
        llm.generate_structured(LLMTask.ANSWER, "s", "p", Out)
