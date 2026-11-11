"""JSM Assets (CMDB): object schemas, object types, attributes and objects."""

import json
from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.clients.jsm.assets_client import DEFAULT_TYPE_IDS
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.assets_ops import (
    AssetObjectTypeDef,
    CreateAssetObjectsParams,
    CreateAssetSchemaParams,
)
from app.schemas.operations.spec import NoParams

BUILT_IN_ATTRIBUTES = {"key", "name", "created", "updated"}


async def workspace_id(ctx: HandlerContext) -> str:
    if "assets_workspace" not in ctx.cache:
        wid = await ctx.jsm.get_assets_workspace_id()
        if not wid:
            raise OperationInputError("This site has no Assets workspace.")
        ctx.cache["assets_workspace"] = wid
    return str(ctx.cache["assets_workspace"])


async def find_schema(ctx: HandlerContext, key: str) -> dict[str, Any] | None:
    for schema in await ctx.assets.list_schemas(await workspace_id(ctx)):
        if str(schema.get("objectSchemaKey", "")).upper() == key.upper():
            return schema
    return None


async def list_schemas(ctx: HandlerContext, _: NoParams) -> HandlerResult:
    schemas = await ctx.assets.list_schemas(await workspace_id(ctx))
    return HandlerResult(
        message=f"{len(schemas)} Assets schema(s).",
        outputs={
            "schemas": [
                {"id": s.get("id"), "key": s.get("objectSchemaKey"), "name": s.get("name")}
                for s in schemas
            ]
        },
    )


async def _icon_id(ctx: HandlerContext, wid: str) -> str:
    if "assets_icon" not in ctx.cache:
        icons = await ctx.assets.list_global_icons(wid)
        if not icons:
            raise OperationInputError("Assets returned no icons for new object types.")
        ctx.cache["assets_icon"] = str(icons[0]["id"])
    return str(ctx.cache["assets_icon"])


async def _ensure_type(
    ctx: HandlerContext,
    wid: str,
    schema_id: str,
    t: AssetObjectTypeDef,
    types: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    existing = types.get(t.name.casefold())
    if existing:
        return existing, False
    payload: dict[str, Any] = {
        "name": t.name,
        "description": t.description,
        "iconId": await _icon_id(ctx, wid),
        "objectSchemaId": schema_id,
    }
    if t.parent:
        parent = types.get(t.parent.casefold())
        if parent is None:
            raise OperationInputError(
                f"Parent object type '{t.parent}' is not defined before '{t.name}'."
            )
        payload["parentObjectTypeId"] = str(parent["id"])
    created = await ctx.assets.create_object_type(wid, payload)
    types[t.name.casefold()] = created
    return created, True


async def create_schema(ctx: HandlerContext, p: CreateAssetSchemaParams) -> HandlerResult:
    wid = await workspace_id(ctx)
    schema = await find_schema(ctx, p.key)
    created_schema = schema is None
    if schema is None:
        schema = await ctx.assets.create_schema(wid, p.name, p.key, p.description)
    elif not same_name(schema.get("name"), p.name):
        raise OperationInputError(f"Assets schema key {p.key} is used by '{schema.get('name')}'.")
    schema_id = str(schema["id"])
    types = {
        str(t["name"]).casefold(): t for t in await ctx.assets.list_object_types(wid, schema_id)
    }
    new_types, new_attrs = 0, 0
    for t in p.object_types:
        object_type, is_new = await _ensure_type(ctx, wid, schema_id, t, types)
        new_types += int(is_new)
        present = {
            str(a["name"]).casefold()
            for a in await ctx.assets.list_attributes(wid, str(object_type["id"]))
        }
        for attr in t.attributes:
            if attr.name.casefold() in present | BUILT_IN_ATTRIBUTES:
                continue
            payload: dict[str, Any] = {
                "name": attr.name,
                "type": 0,
                "defaultTypeId": DEFAULT_TYPE_IDS[attr.type],
            }
            if attr.type == "select":
                if not attr.options:
                    raise OperationInputError(f"Select attribute '{attr.name}' needs options.")
                payload["options"] = ",".join(attr.options)
            await ctx.assets.create_attribute(wid, str(object_type["id"]), payload)
            new_attrs += 1
    url = f"{ctx.site_url}/jira/servicedesk/assets/object-schema/{schema_id}"
    return HandlerResult(
        message=f"{'Created' if created_schema else 'Updated'} Assets schema {p.key} "
        f"({new_types} new object type(s), {new_attrs} new attribute(s)).",
        outputs={"id": schema_id, "key": p.key, "workspace_id": wid, "url": url},
        resource=ResourceRef(type="assets_schema", id=schema_id, key=p.key, title=p.name, url=url),
        reused_existing=not (created_schema or new_types or new_attrs),
    )


def _aql_string(value: str) -> str:
    return json.dumps(value)  # double-quoted, escaped


async def object_type_for(
    ctx: HandlerContext, schema_key: str, type_name: str
) -> tuple[str, dict[str, Any], dict[str, str]]:
    wid = await workspace_id(ctx)
    schema = await find_schema(ctx, schema_key)
    if schema is None:
        raise OperationInputError(f"Assets schema {schema_key} does not exist.")
    for t in await ctx.assets.list_object_types(wid, str(schema["id"])):
        if same_name(t.get("name"), type_name):
            attrs = {
                str(a["name"]).casefold(): str(a["id"])
                for a in await ctx.assets.list_attributes(wid, str(t["id"]))
            }
            return wid, t, attrs
    raise OperationInputError(f"Object type '{type_name}' not found in Assets schema {schema_key}.")


async def find_object(
    ctx: HandlerContext, wid: str, type_id: str, name: str
) -> dict[str, Any] | None:
    found = await ctx.assets.find_objects(
        wid, f"objectTypeId = {type_id} AND Name = {_aql_string(name)}", 1
    )
    return found[0] if found else None


async def create_objects(ctx: HandlerContext, p: CreateAssetObjectsParams) -> HandlerResult:
    wid, object_type, attrs = await object_type_for(ctx, p.schema_key, p.object_type)
    type_id = str(object_type["id"])
    created, reused, keys = 0, 0, []
    for obj in p.objects:
        values = {k.casefold(): v for k, v in obj.attributes.items()}
        name = values.get("name")
        if not name:
            raise OperationInputError('Every Assets object needs a "Name" attribute.')
        existing = await find_object(ctx, wid, type_id, str(name))
        if existing:
            reused += 1
            keys.append(str(existing.get("objectKey")))
            continue
        unknown = [k for k in values if k not in attrs]
        if unknown:
            raise OperationInputError(
                f"Unknown attribute(s) for {p.object_type}: {', '.join(unknown)} "
                f"(available: {', '.join(sorted(attrs))})."
            )
        payload = {
            "objectTypeId": type_id,
            "attributes": [
                {
                    "objectTypeAttributeId": attrs[k],
                    "objectAttributeValues": [
                        {"value": str(v)} for v in (v if isinstance(v, list) else [v])
                    ],
                }
                for k, v in values.items()
            ],
        }
        body = await ctx.assets.create_object(wid, payload)
        keys.append(str(body.get("objectKey")))
        created += 1
    return HandlerResult(
        message=f"{created} {p.object_type} object(s) created, {reused} already existed.",
        outputs={"object_keys": keys, "object_type_id": type_id, "workspace_id": wid},
        reused_existing=created == 0,
    )
