"""Evidence-backed knowledge for Pydantic 1.x -> 2.x (Milestone 2).

Snapshot of the official Pydantic V2 migration guide
(https://docs.pydantic.dev/2.10/migration/), reduced to a small,
representative set of well-documented changes. Every ``MigrationChange``
carries a short verbatim excerpt from that guide, so each claim is
directly checkable against authoritative material.
"""

from ..models import ChangeType, Confidence, Evidence, MigrationChange

TECHNOLOGY = "pydantic"
SOURCE_MAJOR = "1"
TARGET_MAJOR = "2"

_GUIDE_URL = "https://docs.pydantic.dev/2.10/migration/"
_GUIDE = "Pydantic Migration Guide (V1 -> V2)"


def _evidence(section: str, excerpt: str) -> Evidence:
    return Evidence(source=_GUIDE, section=section, excerpt=excerpt, url=_GUIDE_URL)


def changes() -> list[MigrationChange]:
    """The evidence-backed Pydantic 1.x -> 2.x changes known to the agent."""
    return [
        # --- replaced / renamed APIs ---------------------------------------
        MigrationChange(
            change_type=ChangeType.REPLACEMENT,
            old="BaseModel.parse_obj(obj)",
            new="BaseModel.model_validate(obj)",
            description=(
                "The V1 class method parse_obj() was renamed to model_validate() in V2. "
                "Calls such as Model.parse_obj(data) must become Model.model_validate(data)."
            ),
            evidence=_evidence(
                "Changes to pydantic.BaseModel",
                "dict() model_dump() json() model_dump_json() parse_obj() model_validate() "
                "update_forward_refs() model_rebuild()",
            ),
        ),
        MigrationChange(
            change_type=ChangeType.REPLACEMENT,
            old="Model.dict() / Model.json()",
            new="Model.model_dump() / Model.model_dump_json()",
            description=(
                "The instance methods .dict() and .json() were renamed to .model_dump() and "
                ".model_dump_json(); the V1 names are gone in V2 and must be updated."
            ),
            evidence=_evidence(
                "Changes to pydantic.BaseModel",
                "dict() model_dump() json() model_dump_json()",
            ),
        ),
        MigrationChange(
            change_type=ChangeType.REPLACEMENT,
            old="Model.__fields__",
            new="Model.model_fields",
            description=(
                "Internal (dunder) metadata attributes were renamed: __fields__ is now "
                "model_fields (and __fields_set__ is model_fields_set), so code inspecting "
                "model metadata must use the new names."
            ),
            evidence=_evidence(
                "Changes to pydantic.BaseModel",
                "__fields__ model_fields",
            ),
        ),
        MigrationChange(
            change_type=ChangeType.REPLACEMENT,
            old="Field(regex=...)",
            new="Field(pattern=...)",
            description=(
                "The Field() constraint argument regex was renamed to pattern. "
                "Code passing regex='...' to Field() must pass pattern='...' instead."
            ),
            evidence=_evidence(
                "Changes to pydantic.Field",
                "regex (use pattern instead)",
            ),
        ),
        # --- configuration changes -----------------------------------------
        MigrationChange(
            change_type=ChangeType.CONFIGURATION,
            old="class Config: orm_mode = True",
            new="model_config = ConfigDict(from_attributes=True)",
            description=(
                "The Config class setting orm_mode was renamed to from_attributes in the V2 "
                "ConfigDict. ORM attribute loading is now enabled with from_attributes=True."
            ),
            evidence=_evidence(
                "Changes to config",
                "orm_mode from_attributes",
            ),
        ),
        # --- configuration changes (cont.) ---------------------------------
        MigrationChange(
            change_type=ChangeType.CONFIGURATION,
            old="class Config: allow_mutation = False",
            new="model_config = ConfigDict(frozen=True)",
            description=(
                "Config.allow_mutation was removed; its inverse, frozen, now controls model "
                "mutability. Models made immutable via allow_mutation=False should set frozen=True."
            ),
            evidence=_evidence(
                "Changes to config",
                "allow_mutation - this has been removed. You should be able to use frozen "
                "equivalently (inverse of current use).",
            ),
        ),
        # --- removed APIs ----------------------------------------------------
        MigrationChange(
            change_type=ChangeType.REMOVAL,
            old="@root_validator(..., skip_on_failure=...)",
            new=None,
            description=(
                "The skip_on_failure argument of @root_validator was removed. In V2 root "
                "validators no longer accept skip_on_failure; root validation always runs "
                "after field validation for the default (after) mode."
            ),
            evidence=_evidence(
                "Changes to validators",
                "with the deprecated @root_validator decorator, due to refactors in "
                "validation logic, you can no longer run with skip_on_failure=False "
                "(which is the default value of this keyword argument, so must be set "
                "explicitly to True).",
            ),
        ),
        # --- deprecations ----------------------------------------------------
        MigrationChange(
            change_type=ChangeType.DEPRECATION,
            old="@validator",
            new="@field_validator",
            description=(
                "@validator is deprecated in V2 and should be replaced with @field_validator, "
                "which has a new API (ValidationInfo instead of the old keyword arguments)."
            ),
            evidence=_evidence(
                "Changes to validators: @validator and @root_validator are deprecated",
                "@validator has been deprecated, and should be replaced with @field_validator, "
                "which provides various new features and improvements.",
            ),
        ),
        # --- signature changes ------------------------------------------------
        MigrationChange(
            change_type=ChangeType.SIGNATURE,
            old='@validator("f")\ndef f(cls, v, field, config)',
            new='@field_validator("f")\ndef f(cls, v, info: ValidationInfo)',
            description=(
                "Validator functions can no longer declare the field or config keyword "
                "arguments in their signature. Access to that metadata moved to the "
                "ValidationInfo argument (and cls.model_fields) of field_validator."
            ),
            evidence=_evidence(
                "Changes to validators: Changes to @validator's allowed signatures",
                "you can no longer add the field or config arguments to the signature of "
                "validator functions.",
            ),
        ),
        # --- behavior changes --------------------------------------------------
        MigrationChange(
            change_type=ChangeType.BEHAVIOR,
            old="Model __eq__ (V1 semantics)",
            new="Model __eq__ (V2 semantics)",
            description=(
                "Equality semantics tightened: in V2 a model instance can only compare "
                "equal to another BaseModel instance of the same type whose field and "
                "extra values are equal (equality against arbitrary objects is no longer possible)."
            ),
            evidence=_evidence(
                "Changes to pydantic.BaseModel",
                "The __eq__ method has changed for models. Models can only be equal to "
                "other BaseModel instances. For two model instances to be equal, they "
                "must have the same: Type, Field values, Extra values.",
            ),
            confidence=Confidence.HIGH,
        ),
    ]