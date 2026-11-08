"""Request and response bodies."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from app.models import Action, Role

# Emails are compared case-insensitively, so they are stored in lower case.
Email = Annotated[EmailStr, AfterValidator(str.lower)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


def _check_phone(value: str) -> str:
    """Digits with an optional leading +, spaces, dots, dashes and brackets. "" clears it."""
    value = " ".join(value.split())
    if not value:
        return value
    digits = sum(character.isdigit() for character in value)
    if not re.fullmatch(r"\+?[0-9 ().-]+", value) or not 6 <= digits <= 15:
        raise ValueError("enter a phone number of 6 to 15 digits, for example +216 20 123 456")
    return value


Phone = Annotated[str, StringConstraints(max_length=32), AfterValidator(_check_phone)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    phone: str | None = None
    photo_url: str | None = Field(None, description="Profile photo (JPEG), null when none")
    signature_url: str | None = Field(None, description="Signature (PNG), null when none")


# --- sign in, sign up, own account ----------------------------------------------------------


class SignupIn(BaseModel):
    email: Email
    full_name: FullName
    password: Password


class LoginIn(BaseModel):
    # No format or length rule here: a wrong value is simply a failed sign-in.
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class ProfileUpdate(BaseModel):
    """Only the fields that are sent change. A new email needs the current password."""

    full_name: FullName | None = None
    email: Email | None = None
    phone: Phone | None = Field(None, description='"" removes the phone number')
    current_password: str | None = Field(None, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: Password


# --- administration -------------------------------------------------------------------------


class AdminUserCreate(BaseModel):
    email: Email
    full_name: FullName
    password: Password
    role: Role = Role.USER
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    email: Email | None = None
    full_name: FullName | None = None
    role: Role | None = None
    is_active: bool | None = None


class AdminPasswordReset(BaseModel):
    new_password: Password


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


class AdminStats(BaseModel):
    users_total: int
    users_active: int
    users_inactive: int
    admins: int
    signups_last_7_days: int
    active_sessions: int


class ActivityUser(BaseModel):
    """The account that did something, as shown next to its event."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: Role
    is_active: bool
    photo_url: str | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    action: Action
    user: ActivityUser
    target_id: int | None = Field(None, description="Account an administrator acted on")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Counts and changed fields; for administrator actions, the target's "
        "name and email as they were. Never a medicine name or a question.",
    )
    ip: str | None
    user_agent: str | None


class ActivityPage(BaseModel):
    items: list[ActivityOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int] = Field(
        description="Events per action for the same account, search and period, whatever "
        "the action filter: the numbers next to each filter"
    )


# --- catalog --------------------------------------------------------------------------------


class CatalogSummary(BaseModel):
    """Row counts of the processed tables; null when a table has not been built yet."""

    drugs: int | None
    cell_lines: int | None
    synergy_measurements: int | None
    abstracts: int | None


class CatalogPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


# --- Tujya: pills, scan, interactions -------------------------------------------------------
# Every answer about medicines carries its sources and the disclaimer (CLAUDE.md safety rules).

IngredientName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)
]
ClassId = Annotated[int, Field(ge=0, le=9999)]


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    title: str
    url: str
    license: str
    citation: str


class PillOut(BaseModel):
    """One identification class: a C3PI product (NDC9 + part) and its active ingredients."""

    class_id: int
    name: str
    generic_name: str
    labeled_by: str
    imprint: str
    color: str
    shape: str
    active_ingredients: list[str]


class PillList(BaseModel):
    items: list[PillOut]
    total: int
    sources: list[SourceOut]


class PillCandidate(BaseModel):
    class_id: int
    name: str
    generic_name: str
    active_ingredients: list[str]
    probability: float = Field(ge=0, le=1)


class PixelBox(BaseModel):
    """x1, y1 top-left and x2, y2 bottom-right, in pixels of the uploaded image."""

    x1: float
    y1: float
    x2: float
    y2: float


class NormalizedBox(BaseModel):
    """Same box divided by the image width (x) and height (y): values between 0 and 1."""

    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)


class ScannedPill(BaseModel):
    box: PixelBox
    box_normalized: NormalizedBox
    detection_confidence: float = Field(ge=0, le=1)
    candidates: list[PillCandidate] = Field(description="Top-5 classes, most probable first")
    needs_confirmation: bool = Field(
        description="True when the top-1 probability is below confirm_threshold"
    )


class ScanTimings(BaseModel):
    detection_ms: float
    classification_ms: float
    total_ms: float


class ScanResult(BaseModel):
    image_width: int
    image_height: int
    inference_ms: float = Field(description="Detection plus identification, ONNX Runtime")
    timings: ScanTimings
    confirm_threshold: float
    pills: list[ScannedPill]
    message: str | None = None
    models: dict[str, Any]
    sources: list[SourceOut]
    disclaimer: str


class InteractionsIn(BaseModel):
    """At least two things to compare, pill classes (from a scan) and/or ingredient names."""

    pills: list[ClassId] = Field(default_factory=list, max_length=10)
    ingredients: list[IngredientName] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _two_to_ten(self) -> InteractionsIn:
        count = len(self.pills) + len(self.ingredients)
        if not 2 <= count <= 10:
            raise ValueError("give between 2 and 10 pills and ingredients in total")
        return self


class CheckedItem(BaseModel):
    kind: Literal["pill", "ingredient"]
    label: str
    class_id: int | None
    found: bool = Field(description="False when this database does not know the item")
    active_ingredients: list[str]


class InteractionOut(BaseModel):
    ingredient_a: str
    ingredient_b: str
    severity: str = Field(description="DDInter level: Major, Moderate, Minor or Unknown")
    description: str
    source: SourceOut


class PairOut(BaseModel):
    item_a: CheckedItem
    item_b: CheckedItem
    highest_severity: str | None
    interactions: list[InteractionOut]
    shared_ingredients: list[str] = Field(
        description="Active ingredients present in both items (same substance twice)"
    )
    message: str | None = Field(
        description="Set when nothing is listed: no known interaction, or nothing to check"
    )


class InteractionsResult(BaseModel):
    items: list[CheckedItem]
    pairs: list[PairOut]
    highest_severity: str | None
    message: str
    sources: list[SourceOut]
    disclaimer: str


class DemoImage(BaseModel):
    id: int
    class_id: int = Field(description="Class the photo shows (C3PI label), to compare with")
    expected_name: str
    why: str = Field(description="Why it is in the gallery: major, confirm, no-ingredient...")
    url: str
    thumbnail_url: str


class DemoGallery(BaseModel):
    items: list[DemoImage]
    note: str


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000, description="French or English")
    pills: list[int] = Field(
        default_factory=list, max_length=10, description="Confirmed pill class_ids (scan)"
    )
    stream: bool = Field(False, description="Server-Sent Events instead of one JSON answer")


class CitationOut(BaseModel):
    n: int = Field(description="The number used in the answer: [n]")
    title: str
    url: str
    section: str
    snippet: str
    source_name: str
    doc_type: str = Field(description="label, abstract or interaction")
    date: str
    cited: bool = Field(description="True if the answer cites [n]")


class ToolCallOut(BaseModel):
    name: str
    args: dict[str, Any]
    chosen_by: str = Field(description="llm (tool calling) or rule (added by the graph)")
    ok: bool
    summary: str
    round: int = Field(1, description="Retrieval round: 1, then 2+ when the agent searched again")


class ChatResult(BaseModel):
    question: str
    answer: str = Field(description="Checked by the safety node; ends with the disclaimer")
    language: str
    ingredients: list[str] = Field(description="Active ingredients found in the question/pills")
    citations: list[CitationOut]
    tool_calls: list[ToolCallOut]
    safety: dict[str, Any] = Field(description="action ok / rewritten / refused, violations")
    agent: dict[str, Any] = Field(
        default_factory=dict,
        description="planner (rules / llm), retrieval rounds, evidence check, cache hit",
    )
    model: str
    timings: dict[str, float]
    disclaimer: str
    signature: str = Field(
        "",
        description="The server's seal on the question, answer and cited sources: send it "
        "back with them to put this answer in a report (POST /api/my/reports)",
    )


# ---------------------------------------------------------------- toxicity (bonus)


class ToxicityIn(BaseModel):
    molecules: list[str] = Field(
        min_length=1,
        max_length=2,
        description="One or two molecules: active ingredient names or SMILES",
        examples=[["warfarin", "fluconazole"]],
    )


class ToxPrediction(BaseModel):
    task: str = Field(description="Tox21 assay, e.g. SR-p53")
    assay: str
    probability: float = Field(description="Predicted probability of being active in the assay")
    test_roc_auc: float | None = Field(description="The model's ROC-AUC on this assay (test set)")


class ToxMolecule(BaseModel):
    query: str
    resolved_as: Literal["ingredient", "smiles"]
    ingredient: str | None
    smiles: str
    predictions: list[ToxPrediction]
    max_similarity_to_training: float
    in_domain: bool = Field(description="False: far from the training molecules")


class ToxError(BaseModel):
    query: str
    error: str


class ToxicityResult(BaseModel):
    wording: str = Field(description="Always: a model prediction on in vitro tests")
    molecules: list[ToxMolecule] = Field(description="Each molecule on its own")
    errors: list[ToxError]
    mixture_note: str
    low_probability_note: str
    model: dict[str, Any]
    source: dict[str, str]
    disclaimer: str


# --- my medicines and reports (D83) -----------------------------------------------------------


class SavedPillIn(BaseModel):
    class_id: ClassId
    probability: float | None = Field(
        None, ge=0, le=1, description="The model's probability from the scan; null if searched"
    )


class SavedPillOut(BaseModel):
    class_id: int
    name: str
    generic_name: str
    active_ingredients: list[str]
    probability: float | None
    added_at: datetime


class SavedPillList(BaseModel):
    items: list[SavedPillOut] = Field(description="Oldest first, as they were added")
    sources: list[SourceOut]


class CitationRef(BaseModel):
    n: int = Field(ge=0, le=999)
    title: str = Field(max_length=500)
    url: str = Field(max_length=2000)


class ChatExcerptIn(BaseModel):
    """A chat answer to put in a report, exactly as POST /api/chat returned it."""

    question: str = Field(max_length=1000)
    answer: str = Field(max_length=20000)
    citations: list[CitationRef] = Field(
        default_factory=list, max_length=40, description="The cited sources (cited: true)"
    )
    signature: str = Field(max_length=128, description="ChatResult.signature")


class ChatExcerpt(BaseModel):
    question: str
    answer: str
    citations: list[CitationRef]


class ReportIn(BaseModel):
    """Two or more pills (their interactions are checked again now), and/or chat answers."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    pills: list[ClassId] = Field(default_factory=list, max_length=10)
    chat: list[ChatExcerptIn] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _something_to_report(self) -> ReportIn:
        if len(set(self.pills)) < 2 and not self.chat:
            raise ValueError("give at least two different pills or one chat answer")
        return self


class ReportPill(BaseModel):
    class_id: int
    name: str
    generic_name: str
    active_ingredients: list[str]


class ShareState(BaseModel):
    active: bool = Field(description="False once the link has expired or was stopped")
    expires_at: datetime | None
    views: int = Field(description="How many times the shared page was opened")


class ReportBody(BaseModel):
    """What a report says, for its owner and for whoever has its share link."""

    id: int
    created_at: datetime
    title: str
    pills: list[ReportPill]
    interactions: InteractionsResult | None = Field(
        description="Null when the report holds only chat answers"
    )
    chat: list[ChatExcerpt]
    highest_severity: str | None
    author: str = Field(description="Full name of the account that made the report")
    signature: str | None = Field(
        description="The author's signature as a data: URL (PNG), null when none"
    )
    disclaimer: str


class ReportOut(ReportBody):
    share: ShareState | None = Field(description="Null when the report was never shared")


class SharedReport(ReportBody):
    expires_at: datetime


class ReportSummary(BaseModel):
    id: int
    created_at: datetime
    title: str
    pill_names: list[str]
    ingredients: list[str] = Field(
        description="Active ingredients of the pills, each once, sorted: the default title"
    )
    highest_severity: str | None
    pairs_with_interaction: int
    chat_answers: int
    share: ShareState | None


class ReportPage(BaseModel):
    items: list[ReportSummary]
    total: int
    page: int
    page_size: int


class ShareIn(BaseModel):
    days: int = Field(7, ge=1, le=30, description="How long the link works")


class ShareCreated(BaseModel):
    token: str = Field(
        description="Shown this once: the link is /shared#<token>. Only its hash is kept."
    )
    expires_at: datetime


class SharedIn(BaseModel):
    # In the body, not the address, so it never appears in an access log.
    token: str = Field(min_length=10, max_length=100)


# --- administrators' usage report --------------------------------------------------------------


class UsageDay(BaseModel):
    date: str = Field(description="YYYY-MM-DD, in the time zone asked for")
    counts: dict[str, int] = Field(description="Events per action that day")
    active_users: int = Field(description="Accounts that did at least one thing that day")


class UsageReport(BaseModel):
    days: list[UsageDay] = Field(description="Every day of the period, oldest first")
    totals: dict[str, int] = Field(description="Events per action over the period")
    active_users: int = Field(description="Different accounts active over the period")
    new_accounts: int
    reports_saved: int = Field(description="Reports kept at this moment, all accounts")
    shared_now: int = Field(description="Reports with a share link that still works")
