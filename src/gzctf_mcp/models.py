from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

Id = Annotated[int, Field(gt=0)]
Category = Literal[
    "Misc",
    "Crypto",
    "Pwn",
    "Web",
    "Reverse",
    "Blockchain",
    "Forensics",
    "Hardware",
    "Mobile",
    "PPC",
    "AI",
    "Pentest",
    "OSINT",
]
ChallengeType = Literal[
    "StaticAttachment", "StaticContainer", "DynamicAttachment", "DynamicContainer"
]


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    def payload(self):
        return self.model_dump(by_alias=True, exclude_unset=True, mode="json")


class ChallengeCreate(Model):
    title: str = Field(min_length=1)
    category: Category = "Misc"
    type: ChallengeType = "StaticAttachment"


class ChallengeUpdate(Model):
    title: str | None = Field(default=None, min_length=1)
    content: str | None = None
    flag_template: str | None = Field(
        default=None,
        max_length=120,
        description="Dynamic-container flag template; server validates its placeholder rules.",
    )
    category: Category | None = None
    hints: list[str] | None = None
    is_enabled: bool | None = None
    file_name: str | None = None
    deadline_utc: datetime | None = Field(
        default=None,
        description="Timezone-aware ISO deadline. Omit to preserve; use clearDeadline to remove.",
    )
    clear_deadline: bool = Field(
        default=False, description="Remove deadline using the upstream epoch sentinel."
    )
    submission_limit: int | None = Field(default=None, ge=0, le=10000)
    container_image: str | None = None
    memory_limit: int | None = Field(
        default=None, ge=32, le=1048576, description="Memory limit in MB."
    )
    cpu_count: int | None = Field(
        default=None, ge=1, le=1024, description="CPU limit in 0.1 CPU units: 10 = 1 CPU."
    )
    storage_limit: int | None = Field(
        default=None, ge=0, le=1048576, description="Storage limit in MB."
    )
    expose_port: int | None = Field(default=None, ge=1, le=65535)
    network_mode: Literal["Open", "Isolated", "Custom"] | None = None
    enable_traffic_capture: bool | None = None
    disable_blood_bonus: bool | None = None
    original_score: int | None = Field(default=None, ge=0)
    min_score_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    difficulty: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_deadline(self):
        if self.file_name is not None and not self.file_name.strip():
            raise ValueError("fileName must not be empty or whitespace")
        if self.deadline_utc is not None and self.deadline_utc.utcoffset() is None:
            raise ValueError("Use a timezone-aware deadlineUtc")
        if self.clear_deadline and self.deadline_utc is not None:
            raise ValueError("Use clearDeadline or deadlineUtc, not both")
        if (
            "deadline_utc" in self.model_fields_set
            and self.deadline_utc is None
            and not self.clear_deadline
        ):
            raise ValueError("Use clearDeadline=true to remove a deadline")
        return self

    def payload(self):
        body = super().payload()
        body.pop("clearDeadline", None)
        if self.clear_deadline:
            body["deadlineUtc"] = "1970-01-01T00:00:00Z"
        return body


class Attachment(Model):
    attachment_type: Literal["None", "Local", "Remote"] = "None"
    file_hash: str | None = Field(
        default=None,
        description="SHA256; new bindings consume one unused upload from this MCP session. Prefer attachmentPath in deployments.",
    )
    remote_url: str | None = None

    @model_validator(mode="after")
    def check_attachment(self):
        import re
        from urllib.parse import urlsplit

        if (
            self.attachment_type == "Local"
            and not getattr(self, "attachment_path", None)
            and not re.fullmatch("[0-9a-f]{64}", self.file_hash or "")
        ):
            raise ValueError("Local attachment requires a 64-character lowercase SHA256 fileHash")
        if self.attachment_type == "Remote":
            url = urlsplit(self.remote_url or "")
            if url.scheme not in ("http", "https") or not url.hostname or url.username:
                raise ValueError("Remote attachment requires an HTTP(S) URL without credentials")
        return self


class Flag(Attachment):
    attachment_path: str | None = None
    flag: str = Field(min_length=1, max_length=127)

    @model_validator(mode="after")
    def check_path(self):
        if self.attachment_path and (self.attachment_type != "Local" or self.file_hash is not None):
            raise ValueError("Per-flag attachmentPath needs attachmentType=Local and no fileHash")
        return self

    def wire(self):
        return self.model_dump(by_alias=True, exclude_none=True, exclude={"attachment_path"})


class ChallengeManifest(Model):
    challenge: ChallengeCreate
    configuration: ChallengeUpdate = Field(default_factory=ChallengeUpdate)
    flags: list[Flag] = Field(default_factory=list)
    attachment_path: str | None = None
    attachment: Attachment | None = None
    publish: bool = False

    @model_validator(mode="after")
    def validate_workflow(self):
        if self.configuration.is_enabled is not None:
            raise ValueError("Use publish instead of configuration.isEnabled")
        if self.attachment and self.attachment_path:
            raise ValueError("Use attachment or attachmentPath, not both")
        if (
            self.configuration.title is not None
            and self.configuration.title != self.challenge.title
        ):
            raise ValueError(
                "configuration.title must match challenge.title for resumable deployment"
            )
        kind = self.challenge.type
        if self.configuration.enable_traffic_capture and "Container" not in kind:
            raise ValueError("Traffic capture requires a container challenge")
        if len({f.flag for f in self.flags}) != len(self.flags):
            raise ValueError("Duplicate flag strings in manifest")
        if kind == "DynamicContainer" and self.flags:
            raise ValueError("DynamicContainer uses flagTemplate, not manually added flags")
        if kind == "DynamicAttachment" and self.publish:
            if any(f.attachment_type == "None" for f in self.flags):
                raise ValueError("Each dynamic flag must reference its own attachment")
            if not self.configuration.file_name:
                raise ValueError("DynamicAttachment requires a unified fileName")
        if kind == "DynamicAttachment" and (self.attachment_path or self.attachment):
            raise ValueError("DynamicAttachment binds each attachment through its Flag record")
        if self.publish:
            if kind != "DynamicContainer" and not self.flags:
                raise ValueError("Publishing this challenge requires flags")
            if "Container" in kind and not self.configuration.container_image:
                raise ValueError("Publishing a container challenge requires containerImage")
            if kind == "DynamicContainer" and not self.configuration.flag_template:
                raise ValueError("Publishing a dynamic container requires flagTemplate")
        return self


class GameCreate(Model):
    title: str = Field(min_length=1)
    start: datetime
    end: datetime
    hidden: bool = True
    summary: str = ""
    content: str = ""
    accept_without_review: bool = False
    practice_mode: bool = True
    team_member_count_limit: int = Field(default=0, ge=0)
    container_count_limit: int = Field(default=3, ge=0)
    invite_code: str | None = Field(default=None, max_length=32)
    writeup_required: bool = False
    writeup_deadline: datetime | None = None
    writeup_note: str = ""
    blood_bonus: int = Field(
        default=(50 << 20) | (30 << 10) | 10,
        ge=0,
        le=(1 << 30) - 1,
        description="Packed per-mille bonuses: (first << 20) | (second << 10) | third; 50 = 5%.",
    )

    @model_validator(mode="after")
    def check_dates(self):
        if any((self.blood_bonus >> shift) & 1023 > 1000 for shift in (0, 10, 20)):
            raise ValueError("Packed blood bonus entries must be <=1000 per mille")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Use timezone-aware start/end timestamps")
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        if self.writeup_deadline is not None and self.writeup_deadline.tzinfo is None:
            raise ValueError("Use a timezone-aware writeupDeadline")
        if self.writeup_required and not self.writeup_deadline:
            raise ValueError("writeupRequired needs writeupDeadline")
        return self


class BloodBonus(Model):
    """Bonus in per mille: 50 means 5%, matching the official packed integer."""

    first: int = Field(default=50, ge=0, le=1000)
    second: int = Field(default=30, ge=0, le=1000)
    third: int = Field(default=10, ge=0, le=1000)

    def packed(self):
        return (self.first << 20) | (self.second << 10) | self.third


class GamePatch(Model):
    title: str | None = Field(default=None, min_length=1)
    start: datetime | None = None
    end: datetime | None = None
    hidden: bool | None = None
    summary: str | None = None
    content: str | None = None
    accept_without_review: bool | None = None
    practice_mode: bool | None = None
    team_member_count_limit: int | None = Field(default=None, ge=0)
    container_count_limit: int | None = Field(default=None, ge=0)
    invite_code: str | None = Field(default=None, max_length=32)
    writeup_required: bool | None = None
    writeup_deadline: datetime | None = None
    writeup_note: str | None = None
    blood_bonus: BloodBonus | None = None

    @model_validator(mode="after")
    def check_patch(self):
        for name in self.model_fields_set:
            value = getattr(self, name)
            if value is None and name != "invite_code":
                raise ValueError("Only inviteCode may be null")
            if isinstance(value, datetime) and value.utcoffset() is None:
                raise ValueError("Dates must include timezone")
        return self

    def payload(self):
        data = super().payload()
        if self.blood_bonus is not None:
            data["bloodBonus"] = self.blood_bonus.packed()
        return data


Permission = Literal[
    "All",
    "JoinGame",
    "RankOverall",
    "RequireReview",
    "ViewChallenge",
    "SubmitFlags",
    "GetScore",
    "GetBlood",
    "AffectDynamicScore",
]
PERMISSIONS = {
    "All": 2147483647,
    "JoinGame": 1,
    "RankOverall": 2,
    "RequireReview": 4,
    "ViewChallenge": 256,
    "SubmitFlags": 512,
    "GetScore": 1024,
    "GetBlood": 2048,
    "AffectDynamicScore": 4096,
}


def permission_mask(names):
    result = 0
    for name in names:
        result |= PERMISSIONS[name]
    return result


class DivisionChallenge(Model):
    challenge_id: Id
    permissions: list[Permission] = Field(default_factory=lambda: ["All"])

    def payload(self):
        return {"challengeId": self.challenge_id, "permissions": permission_mask(self.permissions)}


class DivisionConfig(Model):
    # Required on updates too: upstream's omitted-name default is an empty string.
    name: str = Field(min_length=1, max_length=31)
    invite_code: str | None = Field(default=None, max_length=32)
    default_permissions: list[Permission] | None = None
    challenge_configs: list[DivisionChallenge] | None = None

    @model_validator(mode="after")
    def unique_challenges(self):
        if self.challenge_configs is not None:
            ids = [c.challenge_id for c in self.challenge_configs]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate challenge IDs in division overrides")
        return self

    def payload(self):
        data = super().payload()
        if self.default_permissions is not None:
            data["defaultPermissions"] = permission_mask(self.default_permissions)
        if self.challenge_configs is not None:
            data["challengeConfigs"] = [c.payload() for c in self.challenge_configs]
        return data


class TeamConfig(Model):
    name: str = Field(min_length=1, max_length=20)
    bio: str | None = Field(default=None, max_length=72)
