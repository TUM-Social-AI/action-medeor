"""Folder-scoped Graph enumeration and change comparison."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol

from app.sharepoint.graph import GraphClient


@dataclass(frozen=True)
class Item:
    item_id: str
    parent_id: str | None
    name: str
    path: str
    web_url: str | None
    etag: str | None
    ctag: str | None
    modified_at: datetime | None
    size_bytes: int | None
    mime_type: str | None
    is_folder: bool
    is_deleted: bool = False
    pending_extraction: bool = False
    last_processed_at: datetime | None = None

    @property
    def is_file(self) -> bool:
        return not self.is_folder


def parse_item(raw: dict, *, prior: Item | None = None, parent_id: str | None = None) -> Item:
    item_id = raw.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("Graph driveItem has no ID")
    parent = raw.get("parentReference") or {}
    raw_date = raw.get("lastModifiedDateTime")
    modified_at = (
        datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        if isinstance(raw_date, str)
        else prior.modified_at
        if prior
        else None
    )
    file_facet = raw.get("file") or {}
    parent_id = parent_id or parent.get("id") or (prior.parent_id if prior else None)
    name = raw.get("name") or (prior.name if prior else "")
    if not name:
        raise ValueError(f"Graph driveItem {item_id} has no name")
    return Item(
        item_id=item_id,
        parent_id=parent_id,
        name=name,
        path=prior.path if prior else "",
        web_url=raw.get("webUrl") or (prior.web_url if prior else None),
        etag=raw.get("eTag") or (prior.etag if prior else None),
        ctag=raw.get("cTag") or (prior.ctag if prior else None),
        modified_at=modified_at,
        size_bytes=raw.get("size", prior.size_bytes if prior else None),
        mime_type=file_facet.get("mimeType") or (prior.mime_type if prior else None),
        is_folder=("folder" in raw or "package" in raw)
        if ("folder" in raw or "package" in raw or "file" in raw)
        else prior.is_folder
        if prior
        else False,
        pending_extraction=prior.pending_extraction if prior else False,
        last_processed_at=prior.last_processed_at if prior else None,
    )


def scoped_tree(items: dict[str, Item], root_id: str) -> dict[str, Item]:
    """Resolve paths from stable parent IDs and discard items outside the granted subtree."""
    if root_id not in items:
        raise ValueError("Configured SharePoint root folder is absent from enumeration")
    root = items[root_id]
    resolved = {root_id: replace(root, parent_id=None, path="")}
    pending = {key: item for key, item in items.items() if key != root_id and not item.is_deleted}
    while pending:
        progressed = False
        for item_id, item in list(pending.items()):
            parent = resolved.get(item.parent_id or "")
            if parent is not None:
                resolved[item_id] = replace(
                    item,
                    path=f"{parent.path}/{item.name}".lstrip("/"),
                )
                del pending[item_id]
                progressed = True
        if not progressed:
            break
    return resolved


class DeltaUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Enumeration:
    items: dict[str, Item]
    mode: Literal["delta", "snapshot"]
    delta_link: str | None


class ChangeSource(Protocol):
    async def enumerate(
        self, root: Item, prior: dict[str, Item], cursor: str | None
    ) -> Enumeration: ...


class FolderSnapshotChangeSource:
    def __init__(self, graph: GraphClient) -> None:
        self.graph = graph

    async def enumerate(
        self, root: Item, prior: dict[str, Item], cursor: str | None
    ) -> Enumeration:
        items = {root.item_id: root}
        folders = [root.item_id]
        while folders:
            folder_id = folders.pop()
            for raw in await self.graph.list_children(folder_id):
                item = parse_item(raw, prior=prior.get(raw.get("id")), parent_id=folder_id)
                items[item.item_id] = item
                if item.is_folder:
                    folders.append(item.item_id)
        return Enumeration(scoped_tree(items, root.item_id), "snapshot", None)


class GraphDeltaChangeSource:
    def __init__(self, graph: GraphClient) -> None:
        self.graph = graph

    async def enumerate(
        self, root: Item, prior: dict[str, Item], cursor: str | None
    ) -> Enumeration:
        raw_changes, link = await self.graph.delta(root.item_id, cursor)
        items = {key: value for key, value in prior.items() if not value.is_deleted}
        items[root.item_id] = root
        for raw in raw_changes:
            item_id = raw.get("id")
            if not isinstance(item_id, str):
                raise DeltaUnavailable("Delta item missing ID")
            if "deleted" in raw:
                items.pop(item_id, None)
                continue
            item = parse_item(raw, prior=items.get(item_id))
            if item.is_file:
                # Business-drive delta can omit cTag; read the changed item directly.
                item = parse_item(await self.graph.get_item(item_id), prior=item)
            items[item_id] = item
        if cursor is not None:
            # A folder moved into the permitted tree can arrive without its descendants.
            for item_id, item in list(items.items()):
                if item.is_folder and item_id != root.item_id and item_id not in prior:
                    subtree = await FolderSnapshotChangeSource(self.graph).enumerate(item, {}, None)
                    items.update(
                        {key: child for key, child in subtree.items.items() if key != item_id}
                    )
        scoped = scoped_tree(items, root.item_id)
        for item_id, item in items.items():
            if item_id not in scoped and item_id not in prior:
                raise DeltaUnavailable(
                    f"Delta returned item {item_id} outside the configured folder tree"
                )
        return Enumeration(scoped, "delta", link)


@dataclass(frozen=True)
class SharePointChange:
    kind: Literal["new", "modified", "metadata", "deleted"]
    item: Item
    previous: Item | None = None


def _content_changed(old: Item, new: Item) -> bool:
    if old.ctag and new.ctag:
        return old.ctag != new.ctag
    if old.etag and new.etag:
        return old.etag != new.etag
    return (old.modified_at, old.size_bytes) != (new.modified_at, new.size_bytes)


def compare(prior: dict[str, Item], current: dict[str, Item]) -> list[SharePointChange]:
    changes: list[SharePointChange] = []
    for item_id, item in current.items():
        if item.is_folder:
            continue
        old = prior.get(item_id)
        if old is None or old.is_deleted:
            changes.append(SharePointChange("new", item, old))
        elif _content_changed(old, item):
            changes.append(SharePointChange("modified", item, old))
        elif (
            old.name,
            old.path,
            old.web_url,
            old.etag,
            old.modified_at,
            old.size_bytes,
            old.mime_type,
        ) != (
            item.name,
            item.path,
            item.web_url,
            item.etag,
            item.modified_at,
            item.size_bytes,
            item.mime_type,
        ):
            changes.append(SharePointChange("metadata", item, old))
    for item_id, old in prior.items():
        if old.is_file and not old.is_deleted and item_id not in current:
            changes.append(SharePointChange("deleted", old, old))
    return changes
