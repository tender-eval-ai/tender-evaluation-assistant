"""The FakeLLM as the build worker's model, behind the gateway as the real client would be:
RULESET_BUILD_LLM_FACTORY=test.rulesets.fake_factory:factory. Scripted for the synthetic
tender: (l) is the certificate, (b) the price schedule with its quantity and one addition
the template lacks (a certificate of analysis), (a) gets one drafted rule, the rest
nothing."""
from app.gateway import Gateway
from app.rulesets import additions as l3b, match as l1, novel as l3, slots as l2
from test.fakes import FakeLLM, Rule
from test.rulesets.test_match import by_item
from test.rulesets.test_novel import SIGNATURE_NODE, SIGNATURE_QUOTE
from test.rulesets.test_slots import answer


def novel_reply(call):
    if "Item (a)" in call.user:
        return l3.Requirements(requirements=[l3.Requirement(name="offer_signed", check="signature", field="offer_signature",
                                                             quote=SIGNATURE_QUOTE, node_id=SIGNATURE_NODE)])
    return l3.Requirements()


ANALYSIS_NODE = "04-Terms-of-Tender-Supplement:5.2"
ANALYSIS_QUOTE = "The Tenderer shall provide a certificate of analysis for each batch within fourteen days of the Purchase Order."
QUOTE_ITEM_1_NODE = "09-Schedules:00-Price-Schedule:PA:(1)"


def additions_reply(call):
    if "Item (b)" in call.user:
        return l3b.Additions(
            additions=[l3.Requirement(name="certificate_of_analysis", check="document_present", field="certificate_of_analysis",
                                      quote=ANALYSIS_QUOTE, node_id=ANALYSIS_NODE)],
            covered=[l3b.Covered(rule_id="price_schedule.unit_price_present", quote="The Tenderer shall quote for Item 1 only.",
                                 node_id=QUOTE_ITEM_1_NODE)])
    return l3b.Additions()


def rules():
    return [Rule(reply=by_item, out_model=l1.Match), Rule(reply=answer(), out_model=l2.SlotFill),
            Rule(reply=novel_reply, out_model=l3.Requirements), Rule(reply=additions_reply, out_model=l3b.Additions)]


def factory(pdir, project, tenderer):
    llm = FakeLLM(rules=rules())
    return Gateway(llm, project=project, data_class="synthetic")
