"""Confluence operations: parameters and catalog entries."""

from typing import Literal

from pydantic import Field

from app.schemas.operations.spec import NoParams, OperationSpec, Params, SpaceKey

_CONF = ("confluence",)

PageKind = Literal[
    "kb_article",
    "it_policy",
    "hr_policy",
    "technical_doc",
    "troubleshooting",
    "sop",
    "project_doc",
    "requirements",
    "how_to",
    "general",
]


class CreateSpaceParams(Params):
    key: SpaceKey
    name: str
    description: str = ""


class UpdateSpaceParams(Params):
    space_key: SpaceKey
    name: str | None = None
    description: str | None = None


class CreatePageParams(Params):
    space_key: SpaceKey
    title: str = Field(min_length=1, max_length=255)
    page_kind: PageKind = "general"
    brief: str = Field(
        default="", description="What the page must cover; the agent writes the content"
    )
    body_storage: str | None = Field(
        default=None, description="Exact Confluence storage-format XHTML (skips generation)"
    )
    parent_page_id: str | None = None
    parent_title: str | None = Field(default=None, description="Parent page title in same space")
    labels: list[str] = Field(default_factory=list)


class UpdatePageParams(Params):
    page_id: str
    title: str | None = None
    brief: str | None = Field(default=None, description="Regenerate content from this brief")
    body_storage: str | None = None
    append_storage: str | None = Field(default=None, description="XHTML appended to the page")
    labels: list[str] = Field(default_factory=list)
    version_message: str = ""


class AddLabelsParams(Params):
    page_id: str
    labels: list[str] = Field(min_length=1)


class CreateIndexPageParams(Params):
    space_key: SpaceKey
    title: str
    introduction: str = ""
    parent_page_id: str | None = None


class SetSpacePermissionParams(Params):
    space_key: SpaceKey
    subject_type: Literal["user", "group"]
    subject: str = Field(description="accountId for users, group name/id for groups")
    operation: Literal["read", "create_page", "create_blogpost", "comment", "administer"]


class DeletePageParams(Params):
    page_id: str


SPECS: list[OperationSpec] = [
    OperationSpec(
        "confluence.list_spaces",
        "confluence",
        "read",
        "List spaces.",
        NoParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.create_space",
        "confluence",
        "create",
        "Create a space.",
        CreateSpaceParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.update_space",
        "confluence",
        "modify",
        "Update space name/description.",
        UpdateSpaceParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.create_page",
        "confluence",
        "create",
        "Create a page: KB article, IT/HR policy, SOP, troubleshooting guide, "
        "technical/project documentation or requirements. Content is written from the "
        "brief with headings, tables and links. Defaults to a child of the space home.",
        CreatePageParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.update_page",
        "confluence",
        "modify",
        "Update a page (new version).",
        UpdatePageParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.add_labels",
        "confluence",
        "modify",
        "Add labels to a page.",
        AddLabelsParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.create_index_page",
        "confluence",
        "create",
        "Create a documentation index page listing its child pages.",
        CreateIndexPageParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.set_space_permission",
        "confluence",
        "security",
        "Grant a user/group a space permission.",
        SetSpacePermissionParams,
        requires_products=_CONF,
    ),
    OperationSpec(
        "confluence.delete_page",
        "confluence",
        "destructive",
        "Move a page to the space trash.",
        DeletePageParams,
        requires_products=_CONF,
    ),
]
