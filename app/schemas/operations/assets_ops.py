"""Jira Service Management Assets (CMDB) operations."""

from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.operations.spec import NoParams, OperationSpec, Params

_ASSETS = ("jira", "jsm", "assets")

SchemaKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$", description="e.g. ITAM")]

AttributeType = Literal[
    "text",
    "textarea",
    "integer",
    "double",
    "boolean",
    "date",
    "datetime",
    "url",
    "email",
    "select",
    "ipaddress",
]


class AssetAttributeDef(Params):
    name: str = Field(min_length=1, max_length=255)
    type: AttributeType = "text"
    options: list[str] = Field(default_factory=list, description="Values for select attributes")


class AssetObjectTypeDef(Params):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    parent: str | None = Field(default=None, description="Parent object type name")
    attributes: list[AssetAttributeDef] = Field(
        default_factory=list, description="Extra attributes (Name/Key/Created/Updated exist)"
    )


class CreateAssetSchemaParams(Params):
    name: str = Field(min_length=1, max_length=255)
    key: SchemaKey
    description: str = ""
    object_types: list[AssetObjectTypeDef] = Field(default_factory=list, max_length=40)


class AssetObjectDef(Params):
    attributes: dict[str, Any] = Field(description='Attribute name → value; must include "Name"')


class CreateAssetObjectsParams(Params):
    schema_key: SchemaKey
    object_type: str
    objects: list[AssetObjectDef] = Field(min_length=1, max_length=100)


SPECS: list[OperationSpec] = [
    OperationSpec(
        "assets.list_schemas",
        "jsm",
        "read",
        "List Assets object schemas.",
        NoParams,
        requires_products=_ASSETS,
    ),
    OperationSpec(
        "assets.create_schema",
        "jsm",
        "create",
        "Create an Assets (CMDB) object schema with object types (hierarchy via parent) and "
        "attributes, e.g. IT assets: Hardware > Laptop/Server, Software, Licences.",
        CreateAssetSchemaParams,
        requires_products=_ASSETS,
    ),
    OperationSpec(
        "assets.create_objects",
        "jsm",
        "create",
        "Create (or reuse by Name) Assets objects of one object type with attribute values.",
        CreateAssetObjectsParams,
        requires_products=_ASSETS,
    ),
]
