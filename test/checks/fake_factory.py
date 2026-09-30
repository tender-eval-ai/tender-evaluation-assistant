"""The FakeLLM as a worker's model, behind the gateway as the real client would be:
VENDOR_CHECK_LLM_FACTORY=test.checks.fake_factory:factory."""
from app.llm.gateway import Gateway
from test.checks.conftest import fake_llm


def factory(pdir, project, tenderer):
    return Gateway(fake_llm(tenderer), project=project, data_class="synthetic")
