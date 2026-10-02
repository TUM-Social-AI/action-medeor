"""File eligibility, folder ancestry and content identity shared by all job modes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePath

from app.core.config import Settings
from app.matching.representation import stable_json_hash
from app.sharepoint.changes import Item


def supported(item: Item) -> bool:
    return (
        item.is_file
        and not item.is_deleted
        and not item.name.startswith("~$")
        and PurePath(item.name).suffix.casefold() in {".pdf", ".xlsx", ".xls"}
    )


def content_version(item: Item) -> str:
    return stable_json_hash(
        [
            item.ctag or item.etag,
            None if item.ctag or item.etag else str(item.modified_at),
            None if item.ctag or item.etag else item.size_bytes,
            PurePath(item.name).suffix.casefold(),
            item.domain,
        ]
    )


def domain_folders(settings: Settings) -> dict[str, str]:
    medicine = settings.sharepoint_medication_folder_id
    equipment = settings.sharepoint_equipment_folder_id
    if not (medicine or equipment) or (medicine and medicine == equipment):
        raise ValueError(
            "Configure at least one domain folder; configured folder IDs must be distinct"
        )
    return {key: value for key, value in ((medicine, "medicine"), (equipment, "equipment")) if key}


def assign_domains(
    items: dict[str, Item], root_id: str, folders: dict[str, str]
) -> dict[str, Item]:
    for folder_id in folders:
        folder = items.get(folder_id)
        if folder is None or not folder.is_folder or folder.parent_id != root_id:
            raise ValueError(
                f"Domain folder {folder_id} must be an immediate folder inside the root"
            )
    resolved = {}
    for item_id, item in items.items():
        ancestor = item
        seen: set[str] = set()
        domain = None
        while ancestor.item_id not in seen:
            seen.add(ancestor.item_id)
            if ancestor.item_id in folders:
                domain = folders[ancestor.item_id]
                break
            if ancestor.parent_id not in items:
                break
            ancestor = items[ancestor.parent_id]
        resolved[item_id] = replace(item, domain=domain)
    return resolved


async def resolve_item(graph, root_id: str, item_id: str, folders: dict[str, str]) -> Item:
    """Read only this item's ancestry and the two domain folders, never enumerate documents."""
    from app.sharepoint.changes import parse_item

    root = parse_item(await graph.get_item(root_id))
    items = {root_id: replace(root, parent_id=None, path="")}
    if not root.is_folder:
        raise ValueError("Configured SharePoint root is not a folder")
    for folder_id in folders:
        items[folder_id] = parse_item(await graph.get_item(folder_id))
    selected = parse_item(await graph.get_item(item_id))
    ancestor = selected
    seen = set()
    while ancestor.item_id != root_id:
        if ancestor.item_id in seen or not ancestor.parent_id:
            raise ValueError("Selected file is outside the permitted SharePoint root")
        seen.add(ancestor.item_id)
        items[ancestor.item_id] = ancestor
        ancestor = items.get(ancestor.parent_id) or parse_item(
            await graph.get_item(ancestor.parent_id)
        )
    from app.sharepoint.changes import scoped_tree

    result = assign_domains(scoped_tree(items, root_id), root_id, folders)[item_id]
    if not supported(result) or result.domain is None:
        raise ValueError(
            "Selected file must be an Excel/PDF offer inside a configured domain folder"
        )
    return result
