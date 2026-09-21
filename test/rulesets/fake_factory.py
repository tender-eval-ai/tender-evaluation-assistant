"""The FakeLLM as the build worker's model, behind the gateway as the real client would be:
RULESET_BUILD_LLM_FACTORY=test.rulesets.fake_factory:factory. Scripted for the synthetic
tender: (l) is the certificate, (b) the price schedule with its quantity, (a) gets one
drafted rule, the rest nothing."""
from app.gateway import Gateway
from app.rulesets import match as l1, novel as l3, slots as l2
from test.fakes import FakeLLM, Rule
from test.rulesets.test_match import by_item
from test.rulesets.test_novel import SIGNATURE_NODE, SIGNATURE_QUOTE
from test.rulesets.test_slots import answer


def novel_reply(call):
    if "Item (a)" in call.user:
        return l3.Requirements(requirements=[l3.Requirement(name="offer_signed", check="signature", field="offer_signature",
                                                             quote=SIGNATURE_QUOTE, node_id=SIGNATURE_NODE)])
    return l3.Requirements()


def factory(pdir, project, tenderer):
    llm = FakeLLM(rules=[Rule(reply=by_item, out_model=l1.Match), Rule(reply=answer(), out_model=l2.SlotFill),
                         Rule(reply=novel_reply, out_model=l3.Requirements)])
    return Gateway(llm, project=project, data_class="synthetic")
