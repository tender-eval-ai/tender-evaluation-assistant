"""The FakeLLM as a worker's model: VENDOR_CHECK_LLM_FACTORY=test.checks.fake_factory:factory."""
from test.checks.conftest import fake_llm


def factory(pdir, project, tenderer):
    return fake_llm(tenderer)
