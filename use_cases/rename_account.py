"""Q-030: rename an account in place, identified by its GUID.

One operation — rename — that gives an account a new name. The new name is a
full account path, so a single rename can change the leaf, the parent, or both
at once. There is no separate "move": placing the account under a different
parent is just what happens when the new name names a different parent.

  - bare leaf  ("Chequing")            → new leaf, same parent
  - full path  ("Assets:Chequing")     → new parent (Assets), same leaf
  - full path  ("Assets:Cash:Petty")   → new parent AND new leaf, together

A surgical book mutation the full plaintext round-trip can't express cleanly.
Every transaction split names its account by *full path*, so renaming an
account through the text would mean rewriting every transaction that references
it — miss one and the file is inconsistent. GnuCash attaches splits to accounts
by *reference* (the account's entity), not by name, so renaming the live
account leaves every split intact; the next export simply prints the new path
wherever the account appears.

Identity is the account GUID (stable across roundtrips since Q-027), never the
old name — the name is precisely what is changing. Any named parent in the new
name must already exist.
"""
from dataclasses import dataclass

from infrastructure.gnucash.guid_lookup import normalise_guid
from infrastructure.gnucash.utils import find_account


@dataclass
class RenameResult:
    # renamed | unchanged | bad_guid | not_found | bad_name | parent_not_found
    # | cycle | name_taken
    status: str
    guid: str = ''
    old_name: str = ''
    new_name: str = ''
    detail: str = ''


def _norm(account) -> str:
    return account.GetGUID().to_string().replace('-', '').lower()


def _colon_name(account) -> str:
    """Full account name in the plaintext convention (colon-separated). GnuCash's
    own `get_full_name()` uses the engine separator, which defaults to '.' in a
    headless book; the plaintext format and `find_account` are colon-based, so
    messages and results use colons too."""
    parts = []
    node = account
    while node is not None and node.get_parent() is not None:
        parts.append(node.GetName())
        node = node.get_parent()
    return ':'.join(reversed(parts))


def _find_account_by_guid(book, guid_norm):
    root = book.get_root_account()
    for acc in root.get_descendants():
        if _norm(acc) == guid_norm:
            return acc
    return None


def _is_self_or_descendant(candidate, account) -> bool:
    """True if `candidate` is `account` itself or sits below it — i.e.
    reparenting `account` under `candidate` would create a cycle. Walks up
    from candidate to the root looking for account."""
    target = _norm(account)
    node = candidate
    while node is not None:
        if _norm(node) == target:
            return True
        node = node.get_parent()
    return False


def execute_rename(book, account_guid, new_name) -> RenameResult:
    try:
        guid_norm = normalise_guid(account_guid)
    except ValueError as e:
        return RenameResult(status='bad_guid', detail=str(e))

    account = _find_account_by_guid(book, guid_norm)
    if account is None:
        return RenameResult(status='not_found', guid=guid_norm)

    old_full = _colon_name(account)
    name = (new_name or '').strip()
    if not name or name.startswith(':') or name.endswith(':'):
        return RenameResult(status='bad_name', guid=guid_norm, old_name=old_full,
                            detail=f'invalid new name {new_name!r}')

    if ':' in name:
        *parent_parts, leaf = name.split(':')
        parent_path = ':'.join(parent_parts)
        new_parent = find_account(book.get_root_account(), parent_path)
        if new_parent is None:
            return RenameResult(status='parent_not_found', guid=guid_norm,
                                old_name=old_full, detail=parent_path)
    else:
        leaf = name
        new_parent = account.get_parent()

    cur_parent = account.get_parent()
    reparenting = _norm(new_parent) != _norm(cur_parent)
    renaming = leaf != account.GetName()
    if not reparenting and not renaming:
        return RenameResult(status='unchanged', guid=guid_norm,
                            old_name=old_full, new_name=old_full)

    if reparenting and _is_self_or_descendant(new_parent, account):
        return RenameResult(status='cycle', guid=guid_norm, old_name=old_full,
                            detail=_colon_name(new_parent))

    # A sibling under the target parent must not already own the new leaf name.
    clash = new_parent.lookup_by_name(leaf)
    if clash is not None and _norm(clash) != guid_norm:
        return RenameResult(status='name_taken', guid=guid_norm, old_name=old_full,
                            detail=f'{_colon_name(new_parent)}:{leaf}')

    if reparenting:
        new_parent.append_child(account)   # moves it; splits stay attached
    if renaming:
        account.SetName(leaf)

    return RenameResult(status='renamed', guid=guid_norm,
                        old_name=old_full, new_name=_colon_name(account))
