# Check kind mapping: AI_camp's 44 check names to 12 CheckTypes

Input for stop point S0 (Nasi, 2026-09-16). Source: the 13 rule files in `agent/src/procurement_agent/validator/rules/` of `nlp4725/Bidding-AI-expert` at commit `7e8e273` (checklist F5). They hold 126 rules using 44 distinct `check` names.

**Result.** 99 rules map to one of the twelve kinds and one splits into two (100 checks). The other 27 are not checks: notes, conditions, gates or normalisations that the schema has to express somewhere else. All twelve kinds are used at least once.

| Kind | Checks |
|---|---|
| `filled` | 51 |
| `human_only` | 11 |
| `range` | 8 |
| `tick_box` | 7 |
| `contains` | 6 |
| `date` | 5 |
| `document_present` | 4 |
| `cross_document_match` | 3 |
| `unit` | 2 |
| `value` | 1 |
| `math` | 1 |
| `signature` | 1 |
| not a rule | 27 |

## By check name

Sorted by number of rules. "per rule" means the name covers rules of different kinds; see the next table.

| AI_camp check | Rules | Kind | Note |
|---|---|---|---|
| `filled` | 47 | `filled` | except `noncollusive_certificate_signed` → `signature` |
| `context` | 12 | not a rule | item note; the `*_conditional_trigger` ones become the item's `condition` |
| `content_criterion` | 8 | per rule | |
| `conditional_filled` | 4 | `filled` | with `condition` |
| `tick_box_declaration` | 4 | `tick_box` | tick (a) comply or (b) propose; blank is deemed compliance |
| `document_form` | 3 | per rule | |
| `umbrella_gate` | 3 | not a rule | a gate over other rules; `depends_on` and the item verdict |
| `conditional_value` | 2 | `range` | days earlier or months longer than the default, with `condition` (option (b) ticked) |
| `deadline_check` | 2 | `date` | deadline = request date + N working days |
| `on_request_trigger` | 2 | not a rule | the item's `condition` ("on request") |
| `range` | 2 | `range` | |
| `self_entry_if_tenderer_is_manufacturer` | 2 | `cross_document_match` | tenderer name or address, with `condition` (tenderer is the manufacturer) |
| `third_party_result` | 2 | `human_only` | the Authority decides (dissatisfaction, plant trial) |
| `unit` | 2 | `unit` | |
| `value` | 2 | per rule | |
| `accredited_body_lookup` | 1 | `human_only` | needs the HKAS register; no list in the repo |
| `bundling_check` | 1 | `document_present` | declaration submitted with the test report |
| `checklist` | 1 | `contains` | label has all 4 required fields |
| `clarification_exception` | 1 | not a rule | outcome policy: a blank essential field is `needs_review`, not `disqualified` |
| `compliance_match` | 1 | `range` | bounds read from the submitted product specs |
| `conditional_explanation` | 1 | `filled` | explanation present, with a `condition` computed by `math` (deviation above threshold) |
| `conditional_requirement` | 1 | `document_present` | legal opinion, with `condition` (overseas sub-contractor, on request) |
| `contains_all_elements` | 1 | `contains` | all 7 elements |
| `contains_all_sections_with_content` | 1 | `contains` | all 16 headings; "non-trivial text" stays with the reviewer |
| `content_check` | 1 | `contains` | independence wording in the declaration |
| `cross_document_match` | 1 | `cross_document_match` | |
| `date_max_age` | 1 | `date` | issue date not before closing date minus 12 months |
| `date_validity_and_presence` | 1 | `date` + `human_only` | split: validity is `date`, the accreditation logo is `human_only` |
| `deadline` | 1 | `date` | request date + 14 calendar days |
| `definitional_carveout` | 1 | not a rule | a definition; a `condition` on the sub-contractor rules |
| `evidence_of_delivery` | 1 | `document_present` | delivery receipt |
| `exactly_one_ticked` | 1 | `tick_box` | `params.exactly_one` |
| `formatting` | 1 | `tick_box` | duplicates `event_disclosure_box_ticked`; merge the two |
| `authority_discretion` | 1 | not a rule | no tenderer action to check |
| `math` | 1 | `math` | |
| `na_allowed` | 1 | not a rule | presence rule: "N/A" counts as filled |
| `overflow_allowed` | 1 | not a rule | extraction hint: read separate sheets |
| `presence_of_accompanying_document` | 1 | `document_present` | schedules of accreditation with the ISO certificate |
| `reference_note` | 1 | not a rule | item note |
| `significant_figures` | 1 | not a rule | normalisation before checking (round to 2 significant figures) |
| `single_number` | 1 | not a rule | normalisation (a range becomes its lower bound) |
| `strike_out_choice` | 1 | `tick_box` | one of two options; blank defaults to cash |
| `substantiation_check` | 1 | `range` | moisture at most 10%, organic content bounds |
| `text_match` | 1 | `contains` | certificate scope includes the product |

## Names that split per rule

| Rule | AI_camp check | Kind | Note |
|---|---|---|---|
| `appendix_tenderer_address_not_postal_box` | `content_criterion` | `contains` | negated: must not contain a P.O. Box |
| `board_resolution_applicability_by_entity_type` | `content_criterion` | not a rule | the item's `condition` by entity type |
| `event_disclosure_details_complete` | `content_criterion` | `human_only` | with `condition` ((b) ticked) |
| `price_schedule_part_c_discount_decimal_precision` | `content_criterion` | `range` | decimal places in [0, 2]; there is no precision kind |
| `sds_bilingual_latest_version` | `content_criterion` | `human_only` | both languages and the latest version |
| `tender_sample_extra_charges` | `content_criterion` | `human_only` | no extra charges proposed |
| `tender_sample_original_packing` | `content_criterion` | `human_only` | manufacturer's original packing |
| `tender_sample_sealed` | `content_criterion` | `human_only` | securely sealed |
| `certified_true_copy_general_mechanism` | `document_form` | not a rule | general mechanism; item note |
| `iso_certificate_original_or_certified_copy` | `document_form` | `human_only` | original or certified copy |
| `test_report_original_or_certified_copy` | `document_form` | `human_only` | original or certified copy |
| `estimated_quantity_value` | `value` | `value` | public-printed constant |
| `tender_sample_quantity` | `value` | `range` | a minimum, so `range` with only `min` |

## Schema gaps and proposed fixes (decide at S0)

The twelve kinds are enough. The gaps are in `TemplateRule` and `RuleSetItem`: each one would lose behaviour the ported engine (`app/engine/`, PR #19) already has. The fixes below reuse the engine's own vocabulary, so the rule-file split at S1 is a rename, not a redesign. They are proposals; `schema.py` changes only in a `contract` PR with both approvals.

| # | Gap | What AI_camp does | Proposed fix |
|---|---|---|---|
| 1 | No outcome per result | outcome entries across the 13 files: 59 `pass`, 29 `needs_review`, 27 `disqualified`, 10 `dormant`, most with a note; `estimated_quantity_value` is `needs_review` when unreadable and `disqualified` on a mismatch | `Outcome` model and `TemplateRule.outcomes: dict[str, Outcome] \| None`; when set it replaces the consequence's defaults whole, as `engine/outcomes.py` does |
| 2 | Three tiers | 7 consequence tiers | `Consequence` enum on `TemplateRule`; `Tier` A/B/C stays on `RuleSetItem.part`, where it means the schedule Part |
| 3 | No normalisation | `significant_figures`, `single_number` run before the check (`surfaced_as: auto_adjustment`) | `TemplateRule.normalise: list[Normalise]` from a closed list, like `CheckType` |
| 4 | `params` strings only | `1102000`, `["HK$", "US$"]` | `dict[str, str \| int \| float \| bool \| list[str]]`; `"{slot}"` references stay strings |
| 5 | No stage | 22 rules tagged Stage I or II; `BidResult` reports both | `TemplateRule.stage: Literal["I", "II"] = "I"` |
| 6 | No item notes or applicability | 27 non-rules hold definitions, triggers and consequences; `exclude_rules` exists because "required only if not the manufacturer" was prose | `RuleSetItem.notes: list[ItemNote]` and `RuleSetItem.condition: str \| None` |
| 7 | Letters vs added items | — | widen `letter` to `^([a-z]\|x[1-9][0-9]*)$`, matching the API contract's open question 2 |

Found while porting the engine: AI_camp's `depends_on` is one rule id (33 rules, all strings, and `engine/depends.py` reads one parent), while `TemplateRule.depends_on` is a list. Proposal: keep the list in the schema and have the engine accept either until the rule files are split.

### Sketch

```python
class Consequence(StrEnum):
    """What a missing or failing field means, before any rule-level override."""
    CRITICAL = "critical"                          # blank → disqualified, redacted → needs_review
    MANDATORY_ON_REQUEST = "mandatory_on_request"  # blank → dormant (may be requested later)
    ON_REQUEST_ONLY = "on_request_only"            # not requested → dormant; requested and missed → disqualified
    DEEMED_COMPLIANCE = "deemed_compliance"        # blank → pass; expressly non-compliant → disqualified
    DEEMED_DEFAULT = "deemed_default"              # blank → pass, read as the stated default (e.g. cash)
    DISCRETIONARY = "discretionary"                # blank → pass; the Authority may ask later
    NO_GATE = "no_gate"                            # recorded, never changes the verdict


class FollowUp(BaseModel):
    trigger: str
    deadline: str                                  # prose, always present
    if_deadline_missed: str


class Outcome(BaseModel):
    status: Literal["pass", "needs_review", "disqualified", "dormant"]
    note: str | None = None                        # may use {field}
    follow_up: FollowUp | None = None              # only with status "dormant"


class Normalise(BaseModel):
    op: Literal["significant_figures", "range_to_lower_bound"]
    params: dict[str, int | float | str] = Field(default_factory=dict)


class ItemNote(BaseModel):
    kind: Literal["definition", "trigger", "consequence", "reference"]
    text: str = Field(min_length=1)
    citation: Citation | None = None


class TemplateRule(BaseModel):
    ...                                            # existing fields
    params: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    consequence: Consequence                       # replaces `tier`
    outcomes: dict[str, Outcome] | None = None     # overrides the consequence's defaults whole
    normalise: list[Normalise] = Field(default_factory=list)
    stage: Literal["I", "II"] = "I"


class RuleSetItem(BaseModel):
    letter: str = Field(pattern=r"^([a-z]|x[1-9][0-9]*)$")
    ...
    condition: str | None = Field(default=None, description="the item applies only when this holds")
    notes: list[ItemNote] = Field(default_factory=list)
```

The comments are typical defaults only. AI_camp defines `consequence_tiers` per rule file and they differ: `critical` sometimes adds `not_applicable → needs_review`, `on_request_only` has two vocabularies, `discretionary` is empty in one file. So the default outcomes stay per template (`app/rulesets/templates/<form>.json`, `consequences` key), as they are per file today, not in one global table.

Open for S0: whether `condition` stays a free string the checker resolves (as `exclude_rules` does today) or becomes a small expression over vendor fields. Proposal: a free string now, an expression after S3 if evals show conditions are misapplied.
