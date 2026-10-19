import io
from collections.abc import Iterator
from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from labcatalog import defaults
from labcatalog.metadata import editing, records


def blocks(data) -> Iterator[CommentedMap]:
    # Every custom: mapping in a file, wherever its owner sits.
    if isinstance(data, dict):
        for key, value in data.items():
            if key == records.CUSTOM and isinstance(value, dict):
                yield value
            else:
                yield from blocks(value)
    elif isinstance(data, list):
        for value in data:
            yield from blocks(value)


def field_defs(text: str) -> list[dict]:
    data = records.load(text)
    return [f for f in (data.get("custom_fields") or []) if isinstance(f, dict)]


def field_names(text: str) -> list[str]:
    return [f.get("name") for f in field_defs(text)]


def field_changes(old_text: str, new_text: str) -> tuple[dict[str, str], list[str]]:
    # A field whose name changed in place is renamed; one that is gone is removed.
    old, new = field_names(old_text), field_names(new_text)
    if len(old) == len(new):
        return {o: n for o, n in zip(old, new, strict=True) if o != n and o not in new}, []
    return {}, [o for o in old if o not in new]


def option_changes(
    old_text: str, new_text: str, renames: dict[str, str]
) -> dict[str, dict[str, str]]:
    # Per field, by its new name: each choice renamed in place; a choice taken out stays in the data.
    old = {f.get("name"): f.get("choices") or [] for f in field_defs(old_text)}
    found = {}
    for new in field_defs(new_text):
        name = new.get("name")
        before = old.get(next((o for o, n in renames.items() if n == name), name), [])
        after = new.get("choices") or []
        if len(before) == len(after):
            changed = {
                str(o): str(n)
                for o, n in zip(before, after, strict=True)
                if o != n and o not in after
            }
            if changed:
                found[name] = changed
    return found


def renamed(value, options: dict[str, str]):
    # A choice holds one option and a tags field a list of them.
    if isinstance(value, list):
        return [options.get(str(v), v) for v in value]
    return options.get(str(value), value)


def changed_values(
    text: str,
    renames: dict[str, str],
    removed: list[str],
    options: dict[str, dict[str, str]] | None = None,
) -> str | None:
    # The file with the fields' values renamed or removed; None when it holds none of them.
    data = records.round_trip().load(text)
    touched = False
    for block in blocks(data):
        for old in [k for k in block if k in renames or k in removed]:
            value = block.pop(old)
            if old in renames:
                block[renames[old]] = value
            touched = True
        for name, chosen in (options or {}).items():
            if name in block and renamed(block[name], chosen) != block[name]:
                value = renamed(block[name], chosen)
                if isinstance(value, list):
                    block[name][:] = value
                else:
                    block[name] = value
                touched = True
    # The Instruments page's filters name fields too.
    facets = (data.get("browse") or {}).get("facets") if isinstance(data, dict) else None
    if facets is not None and any(f in renames or f in removed for f in facets):
        facets[:] = [renames.get(f, f) for f in facets if f not in removed]
        touched = True
    if not touched:
        return None
    out = io.StringIO()
    records.round_trip().dump(data, out)
    return out.getvalue()


def files(root: Path) -> list[str]:
    found = editing.editable_files(root)
    return [p for group, paths in found.items() if group != "Column maps" for p in paths]


def field_uses(root: Path, names: list[str]) -> dict[str, int]:
    counts = dict.fromkeys(names, 0)
    for relative in files(root):
        data = records.load((root / relative).read_text(encoding="utf-8"))
        for block in blocks(data):
            for name in names:
                counts[name] += name in block
    return counts


def option_uses(
    root: Path, options: dict[str, dict[str, str]], renames: dict[str, str]
) -> dict[tuple[str, str], int]:
    # How many owners hold each renamed option, under the field's new name or its old one.
    before = {new: old for old, new in renames.items()}
    counts = {(name, old): 0 for name, chosen in options.items() for old in chosen}
    for relative in files(root):
        data = records.load((root / relative).read_text(encoding="utf-8"))
        for block in blocks(data):
            for name, old in counts:
                value = block.get(name, block.get(before.get(name)))
                held = value if isinstance(value, list) else [value]
                counts[name, old] += old in [str(v) for v in held]
    return counts


def apply_elsewhere(
    root: Path,
    renames: dict[str, str],
    removed: list[str],
    options: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    # Every file but labcatalog.yaml, which the caller saves with its own changes.
    saved = []
    for relative in files(root):
        if relative == defaults.CONFIG_FILENAME:
            continue
        opened = editing.open_file(root, relative)
        text = changed_values(opened.text, renames, removed, options)
        if text is not None:
            editing.save_file(root, opened, text)
            saved.append(relative)
    return saved
